"""FastAPI: health, stream status, detector status, NL video search,
subscription signup API, landing page + storefront static mounts."""
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from marketplace.api_runtime import APIRuntimeError

ROOT = Path("/app")
LANDING = ROOT / "landing"
STOREFRONT = ROOT / "storefront"
GUIDE = ROOT / "guide"
SETUP = ROOT / "setup"
ASSETS = ROOT / "assets"
DOOR_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
FUNCTION_ID_RE = r"^[a-z0-9][a-z0-9-]{0,127}$"
REQUEST_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class ClipExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function_id: str = Field(min_length=1, max_length=128, pattern=FUNCTION_ID_RE)
    camera_id: str = Field(min_length=1, max_length=128, pattern=REQUEST_ID_RE)
    start_ms: int = Field(ge=1, le=9_999_999_999_999)
    end_ms: int = Field(ge=1, le=9_999_999_999_999)


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function_id: str = Field(min_length=1, max_length=128, pattern=FUNCTION_ID_RE)
    camera_id: str = Field(min_length=1, max_length=128, pattern=REQUEST_ID_RE)
    request_id: str = Field(min_length=1, max_length=128, pattern=REQUEST_ID_RE)


class AuditedUnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function_id: str = Field(min_length=1, max_length=128, pattern=FUNCTION_ID_RE)
    door_id: str = Field(min_length=1, max_length=128, pattern=REQUEST_ID_RE)
    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=128, pattern=REQUEST_ID_RE)


class SignupRateLimiter:
    """Per-source sliding-window limiter with an LRU-bounded source table."""

    def __init__(self, limit: int, window_seconds: float = 60, max_sources: int = 10000):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self.max_sources = max(1, int(max_sources))
        self._attempts = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            expired = [source for source, values in self._attempts.items() if not values or values[-1] <= cutoff]
            for source in expired:
                self._attempts.pop(source, None)

            attempts = self._attempts.pop(key, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts and len(self._attempts) >= self.max_sources:
                self._attempts.popitem(last=False)
            self._attempts[key] = attempts
            if len(attempts) >= self.limit:
                return False
            attempts.append(current)
            return True

    def tracked_source_count(self) -> int:
        with self._lock:
            return len(self._attempts)


def authorize_control_request(authorization: Optional[str]) -> None:
    """Fail closed unless a configured bearer token authorizes door control."""
    expected = os.environ.get("VISION_CONTROL_TOKEN", "")
    if not expected or "change-me" in expected.lower():
        raise HTTPException(status_code=503, detail="Door control is disabled")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Valid bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def authorize_operational_request(x_admin_token: str | None) -> None:
    """Protect camera metadata and compute-heavy operational routes."""
    expected = os.environ.get("VISION_ADMIN_TOKEN", "")
    if not expected or "change-me" in expected.lower():
        raise HTTPException(status_code=503, detail="Operational API is disabled")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Valid admin token required")


def detector_status_payload(camera_detectors):
    """Return configured runtime IDs without exposing detector internals."""
    return {
        camera_id: [detector.name for detector in detectors]
        for camera_id, detectors in camera_detectors.items()
    }


def create_app(pipeline, streams, *, setup_service=None, restart_callback=None):
    app = FastAPI(title="nexus-vision-ai", version="0.2.0")
    license_service = getattr(pipeline, "license_service", None)

    if setup_service is None:
        from setup_service import SetupService, SetupStore

        config_path = Path(os.environ.get("VISION_CONFIG", "/config/sites.yaml"))
        settings_path = Path(os.environ.get("VISION_RUNTIME_SETTINGS", "/config/runtime-settings.json"))
        available = getattr(pipeline, "available_detector_ids", None)
        setup_service = SetupService(
            SetupStore(config_path, settings_path, settings_path.parent / "certs"),
            allowed_detectors=set(available) if available is not None else None,
            configuration_validator=(
                license_service.validate_configuration if license_service is not None else None
            ),
        )
    from setup_api import build_setup_router
    app.include_router(
        build_setup_router(
            setup_service,
            authorize_operational_request,
            restart_callback=restart_callback,
        )
    )
    if license_service is not None:
        from activation.api import build_licensing_router

        app.include_router(build_licensing_router(license_service, authorize_operational_request))

    @app.exception_handler(RequestValidationError)
    async def redact_setup_validation_errors(request: Request, exc: RequestValidationError):
        if request.url.path.startswith(("/api/setup/", "/api/licensing/", "/api/functions/")):
            if request.url.path.startswith("/api/licensing/"):
                label = "licensing"
            elif request.url.path.startswith("/api/functions/"):
                label = "function"
            else:
                label = "setup"
            return JSONResponse({"detail": f"Invalid {label} request"}, status_code=422)
        return JSONResponse({"detail": jsonable_encoder(exc.errors())}, status_code=422)

    app.state.signup_rate_limiter = SignupRateLimiter(
        int(os.environ.get("VISION_SIGNUP_RATE_LIMIT_PER_MINUTE", "5")),
        max_sources=int(os.environ.get("VISION_SIGNUP_RATE_LIMIT_MAX_SOURCES", "10000")),
    )
    signup_max_body_bytes = max(1024, int(os.environ.get("VISION_SIGNUP_MAX_BODY_BYTES", "32768")))
    setup_max_body_bytes = max(1024, int(os.environ.get("VISION_SETUP_MAX_BODY_BYTES", "65536")))
    licensing_max_body_bytes = max(
        1024, int(os.environ.get("VISION_LICENSING_MAX_BODY_BYTES", "73728"))
    )

    def current_alert_delivery():
        default = {
            "ok": True,
            "configured": [],
            "degraded_destinations": [],
            "pending_events": 0,
            "pending_occurrences": 0,
            "dropped": 0,
        }
        reporter = getattr(pipeline.alerts, "delivery_readiness", None)
        return reporter() if reporter else default

    def current_licensing():
        if not getattr(pipeline, "licensing_enforced", False):
            return {"state": "not_enforced", "reason": "not_enforced", "paid_runtime_authorized": True}
        authorization = getattr(pipeline, "license_authorization", None)
        if authorization is None:
            return {
                "state": "invalid",
                "reason": "authorization_unavailable",
                "paid_runtime_authorized": False,
            }
        state = getattr(authorization, "state", "invalid")
        return {
            "state": state,
            "reason": getattr(authorization, "reason", "unknown"),
            "paid_runtime_authorized": (
                getattr(authorization, "authorized", False) is True
                and state in {"current", "grace"}
            ),
        }

    @app.middleware("http")
    async def bound_public_signup_body(request: Request, call_next):
        body_limit = None
        body_label = "request"
        if request.method == "POST" and request.url.path == "/api/subscriptions":
            body_limit = signup_max_body_bytes
            body_label = "signup request"
        elif request.method == "POST" and request.url.path.startswith("/api/setup/"):
            body_limit = setup_max_body_bytes
            body_label = "setup request"
        elif request.method == "POST" and request.url.path.startswith("/api/licensing/"):
            body_limit = licensing_max_body_bytes
            body_label = "licensing request"
        elif request.method == "POST" and request.url.path.startswith("/api/functions/"):
            body_limit = 16 * 1024
            body_label = "function request"
        if body_limit is not None:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > body_limit:
                        return JSONResponse({"detail": f"{body_label} is too large"}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "invalid content length"}, status_code=400)

            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > body_limit:
                    return JSONResponse({"detail": f"{body_label} is too large"}, status_code=413)

            # BaseHTTPMiddleware's downstream receive wrapper replays `_body`.
            # Replacing `_receive` after stream consumption leaves the wrapper
            # consumed and gives request validation an empty body.
            request._body = bytes(body)
        return await call_next(request)

    # ── subscription platform + storefront ──
    from subscriptions import store
    from subscriptions.app import router as sub_router
    store.init_db()
    app.include_router(sub_router)
    if ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="public-assets")

    if LANDING.exists():

        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        def landing():
            return FileResponse(str(LANDING / "index.html"))

    if STOREFRONT.exists():
        app.mount("/storefront", StaticFiles(directory=str(STOREFRONT), html=True), name="storefront")
    if GUIDE.exists():
        app.mount("/guide", StaticFiles(directory=str(GUIDE), html=True), name="guide")
    if SETUP.exists():
        app.mount("/setup", StaticFiles(directory=str(SETUP), html=True), name="setup")

    @app.get("/health")
    def health():
        up = sum(1 for w in streams.workers if w.connected)
        alert_delivery = current_alert_delivery()
        return {
            "ok": True,
            "site": pipeline.site,
            "streams_up": up,
            "streams_total": len(streams.workers),
            "alerts": pipeline.alerts.stats(),
            "alert_destinations": getattr(pipeline.alerts, "destination_stats", lambda: {})(),
            "alert_delivery": alert_delivery,
            "licensing": current_licensing(),
        }

    @app.get("/ready")
    def readiness():
        configured_total = len(getattr(pipeline, "cameras", []))
        max_frame_age = max(1.0, float(os.environ.get("VISION_READY_MAX_FRAME_AGE_SECONDS", "30")))
        now = time.time()
        up = sum(
            1
            for worker in streams.workers
            if worker.connected
            and getattr(worker, "last_frame_at", None) is not None
            and 0 <= now - worker.last_frame_at <= max_frame_age
        )
        detector_failures = getattr(pipeline, "detector_failures", {})
        alert_delivery = current_alert_delivery()
        licensing = current_licensing()
        authorization = getattr(pipeline, "license_authorization", None)
        license_runtime_ok = (
            not getattr(pipeline, "licensing_enforced", False)
            or getattr(pipeline, "requested_detector_count", 0) == 0
            or (
                getattr(authorization, "authorized", False) is True
                and licensing.get("paid_runtime_authorized") is True
            )
        )
        ready = (
            configured_total > 0
            and len(streams.workers) == configured_total
            and up == configured_total
            and not detector_failures
            and alert_delivery.get("ok") is True
            and license_runtime_ok
        )
        payload = {
            "ok": ready,
            "site": pipeline.site,
            "streams_up": up,
            "streams_total": configured_total,
            "detectors_failed": len(detector_failures),
            "alert_delivery": alert_delivery,
            "licensing": licensing,
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/streams")
    def stream_status(x_admin_token: str | None = Header(default=None)):
        authorize_operational_request(x_admin_token)
        return streams.status()

    @app.get("/detectors")
    def detector_status(x_admin_token: str | None = Header(default=None)):
        authorize_operational_request(x_admin_token)
        return detector_status_payload(pipeline.camera_detectors)

    @app.get("/search")
    def search(
        q: str = Query(..., min_length=2, max_length=200),
        limit: int = Query(10, ge=1, le=50),
        x_admin_token: str | None = Header(default=None),
    ):
        authorize_operational_request(x_admin_token)
        if getattr(pipeline, "licensing_enforced", False):
            if license_service is None or not license_service.allows_function("video_search"):
                raise HTTPException(
                    status_code=403,
                    detail="Current signed entitlement does not grant video search",
                )
        from detectors.video_search import search as vs_search
        return {"query": q, "results": vs_search(q, limit=limit)}

    def api_runtime():
        runtime = getattr(pipeline, "api_runtime", None)
        if runtime is None:
            raise HTTPException(status_code=503, detail="API function runtime is unavailable")
        return runtime

    def authorize_function(function_id: str, *, capability: str | None = None):
        if not getattr(pipeline, "licensing_enforced", False):
            return
        if license_service is None or not license_service.allows_function(function_id):
            raise HTTPException(
                status_code=403,
                detail="Current signed entitlement does not grant this function",
            )
        if capability and not license_service.allows_capability(capability):
            raise HTTPException(
                status_code=403,
                detail="Current signed entitlement does not grant access control",
            )

    def reject_runtime_error(exc: APIRuntimeError):
        if exc.code in {"duplicate_request", "duplicate_snapshot_request"}:
            status = 409
        elif exc.code in {"function_not_configured", "camera_not_configured", "door_not_allowed"}:
            status = 403
        elif exc.code.endswith("_unavailable"):
            status = 503
        elif exc.code in {"clip_export_failed", "clip_too_large", "snapshot_write_failed", "unlock_failed"}:
            status = 502
        else:
            status = 400
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": "Function request rejected"},
        ) from None

    @app.post("/api/functions/protect/clip-export")
    def export_protect_clip(
        request: ClipExportRequest,
        x_admin_token: str | None = Header(default=None),
    ):
        authorize_operational_request(x_admin_token)
        authorize_function(request.function_id)
        try:
            return api_runtime().export_clip(
                request.function_id,
                request.camera_id,
                request.start_ms,
                request.end_ms,
            )
        except APIRuntimeError as exc:
            reject_runtime_error(exc)

    @app.post("/api/functions/protect/snapshot")
    def capture_protect_snapshot(
        request: SnapshotRequest,
        x_admin_token: str | None = Header(default=None),
    ):
        authorize_operational_request(x_admin_token)
        authorize_function(request.function_id)
        try:
            return api_runtime().request_snapshot(
                request.function_id,
                request.camera_id,
                request_id=request.request_id,
            )
        except APIRuntimeError as exc:
            reject_runtime_error(exc)

    @app.post("/api/functions/access/unlock")
    def audited_access_unlock(
        request: AuditedUnlockRequest,
        x_admin_token: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        authorize_operational_request(x_admin_token)
        authorize_control_request(authorization)
        authorize_function(request.function_id, capability="access-control")
        try:
            return api_runtime().request_unlock(
                request.function_id,
                request.door_id,
                reason=request.reason,
                request_id=request.request_id,
            )
        except APIRuntimeError as exc:
            reject_runtime_error(exc)

    @app.post("/unlock/{door_id}")
    def unlock_door(door_id: str, authorization: str | None = Header(default=None)):
        authorize_control_request(authorization)
        if not DOOR_ID_RE.fullmatch(door_id):
            raise HTTPException(status_code=400, detail="Invalid door identifier")
        raise HTTPException(
            status_code=410,
            detail="Legacy unlock route is disabled; use the audited function request endpoint",
        )

    return app
