"""Nexus Vision AI entrypoint: config → streams → detectors → alerts → API."""
import copy
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

import yaml

from activation import LicenseService, LicenseValidationError, RuntimeAuthorization
from activation.runtime import build_license_service
from alerts import AlertEngine
from detectors.base import DETECTOR_REGISTRY
from marketplace.contract import detection_scope
from marketplace.api_runtime import APIFunctionRuntime
from marketplace.loader import load_all as load_marketplace_functions
from marketplace.runtime import build_camera_detectors
from process_control import setup_restart_callback
from site_time import require_site_timezone
from streams import StreamManager
from unifi_access import AccessPoller
from unifi_protect import ProtectClient, ProtectEventPoller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


def load_detectors():
    import detectors.fall          # noqa: F401
    import detectors.bed_exit      # noqa: F401
    import detectors.weapon        # noqa: F401
    import detectors.ppe           # noqa: F401
    import detectors.near_miss     # noqa: F401
    import detectors.elopement     # noqa: F401
    import detectors.alpr          # noqa: F401
    import detectors.video_search  # noqa: F401
    import detectors.tailgating    # noqa: F401
    import detectors.smoke_flame   # noqa: F401

    marketplace_registry, errors = load_marketplace_functions()
    if errors:
        details = "; ".join(f"{name}: {error}" for name, error in sorted(errors.items()))
        raise RuntimeError(f"marketplace function loading failed: {details}")
    overlap = set(DETECTOR_REGISTRY).intersection(marketplace_registry)
    if overlap:
        raise RuntimeError(f"detector id collision: {', '.join(sorted(overlap))}")
    return {
        **DETECTOR_REGISTRY,
        **{function_id: entry["cls"] for function_id, entry in marketplace_registry.items()},
    }


def _detector_signature(camera_detectors):
    return tuple(
        (camera_id, tuple(detector.name for detector in detectors))
        for camera_id, detectors in sorted(camera_detectors.items())
    )


def _fail_closed_authorization(config: dict, reason: str) -> RuntimeAuthorization:
    """Disable every requested function without exposing refresh exception details."""
    effective = copy.deepcopy(config)
    requested: set[str] = set()
    stream_count = 0
    cameras = effective.get("cameras", []) if isinstance(effective, dict) else []
    if not isinstance(cameras, list):
        cameras = []
        effective["cameras"] = cameras
    for camera in cameras:
        if not isinstance(camera, dict):
            continue
        detectors = camera.get("detectors", [])
        if isinstance(detectors, list):
            valid_ids = {item for item in detectors if isinstance(item, str)}
            requested.update(valid_ids)
            if valid_ids:
                stream_count += 1
        camera["detectors"] = []
    return RuntimeAuthorization(
        authorized=False,
        state="invalid",
        reason=reason,
        effective_config=effective,
        stream_count=stream_count,
        distinct_function_count=len(requested),
        granted_function_ids=frozenset(),
    )


class Pipeline:
    def __init__(self, config: dict, detector_classes=None, *, license_service=None):
        self.config = config
        self.site = config.get("site", {}).get("name", "site")
        self.timezone = require_site_timezone(config)
        self.alerts = AlertEngine(config, os.environ.get("VISION_DATA", "/app/data"))
        self.access_events = deque(maxlen=500)
        self.protect_events = deque(maxlen=1000)

        classes = DETECTOR_REGISTRY if detector_classes is None else detector_classes
        self.available_detector_ids = set(classes)
        self._api_registry = {
            function_id: {"manifest": cls.api_manifest, "cls": cls}
            for function_id, cls in classes.items()
            if getattr(cls, "api_function", False)
        }
        self.license_service = license_service
        self.licensing_enforced = license_service is not None
        self.requested_detector_count = sum(
            len(camera.get("detectors", []))
            for camera in config.get("cameras", [])
            if isinstance(camera, dict) and isinstance(camera.get("detectors", []), list)
        )
        if license_service is not None:
            self.license_authorization = license_service.authorize_configuration(config)
            effective_config = self.license_authorization.effective_config
            self.entitled_detector_ids = (
                set(self.license_authorization.granted_function_ids).intersection(classes)
                if self.license_authorization.authorized
                else set()
            )
        else:
            self.license_authorization = None
            effective_config = config
            self.entitled_detector_ids = set(classes)

        self.effective_config = effective_config
        self.cameras = effective_config.get("cameras", [])
        self.settings = effective_config.get("detector_settings", {})
        self._detector_lock = threading.RLock()
        self.camera_detectors = build_camera_detectors(self.cameras, self.settings, classes)
        self._detector_classes = classes
        self.detector_failures = {}
        self.api_runtime = self._build_api_runtime(effective_config)

    def _build_api_runtime(self, config: dict, previous=None):
        if not self._api_registry:
            return None
        evidence_root = (
            os.environ.get("VISION_EVIDENCE")
            or os.environ.get("VISION_EVIDENCE_DIR")
            or str(Path(os.environ.get("VISION_DATA", "/app/data")) / "evidence")
        )
        return APIFunctionRuntime(
            config,
            self._api_registry,
            alerts=self.alerts,
            site=self.site,
            evidence_root=evidence_root,
            protect_client=getattr(previous, "protect_client", None),
            access_control=getattr(previous, "access_control", None),
            clock=time.time,
        )

    def refresh_license(self) -> bool:
        """Re-evaluate the signed lease and atomically disable/restore detector instances."""
        if self.license_service is None:
            return False
        try:
            authorization = self.license_service.authorize_configuration(self.config)
        except Exception:
            log.error("license authorization refresh unavailable; paid analytics disabled")
            authorization = _fail_closed_authorization(
                self.config, "license_refresh_error"
            )
        effective_config = authorization.effective_config
        new_detectors = build_camera_detectors(
            effective_config.get("cameras", []),
            effective_config.get("detector_settings", {}),
            self._detector_classes,
        )
        new_api_runtime = self._build_api_runtime(effective_config, self.api_runtime)
        previous = (
            getattr(self.license_authorization, "state", None),
            getattr(self.license_authorization, "reason", None),
            _detector_signature(self.camera_detectors),
        )
        current = (
            authorization.state,
            authorization.reason,
            _detector_signature(new_detectors),
        )
        with self._detector_lock:
            self.license_authorization = authorization
            self.effective_config = effective_config
            self.cameras = effective_config.get("cameras", [])
            self.settings = effective_config.get("detector_settings", {})
            self.camera_detectors = new_detectors
            self.api_runtime = new_api_runtime
            self.entitled_detector_ids = (
                set(authorization.granted_function_ids).intersection(self._detector_classes)
                if authorization.authorized
                else set()
            )
        return current != previous

    def on_access_event(self, event: dict):
        self.access_events.append(event)
        if self.api_runtime is not None:
            self.api_runtime.on_access_event(event)

    def attach_api_adapters(self, *, protect_client=None, access_control=None):
        with self._detector_lock:
            if self.api_runtime is not None:
                self.api_runtime.attach_adapters(
                    protect_client=protect_client,
                    access_control=access_control,
                )

    def on_protect_inventory(self, cameras, *, api_latency_ms=None):
        with self._detector_lock:
            api_runtime = self.api_runtime
        if api_runtime is not None:
            api_runtime.on_inventory(cameras, api_latency_ms=api_latency_ms)

    def on_protect_poll(self, status: dict):
        with self._detector_lock:
            api_runtime = self.api_runtime
        if api_runtime is not None:
            api_runtime.on_protect_poll(status)

    def on_protect_event(self, event: dict):
        self.protect_events.append(event)
        if self.api_runtime is not None:
            self.api_runtime.on_protect_event(event)

    def on_stream_status(self, camera: dict, status: dict, ts: float):
        with self._detector_lock:
            api_runtime = self.api_runtime
        if api_runtime is not None:
            api_runtime.on_stream_status(camera, status, ts)

    def on_frame(self, camera: dict, frame, ts: float):
        # Detectors receive the frame for pose extraction; AlertEngine centrally
        # suppresses snapshots when privacy_mode is skeleton.
        with self._detector_lock:
            detectors = tuple(self.camera_detectors.get(camera["id"], []))
            api_runtime = self.api_runtime
        if api_runtime is not None:
            api_runtime.on_frame(camera, frame, ts)
        for det in detectors:
            key = f"{camera['id']}:{det.name}"
            try:
                with detection_scope((camera["id"], det.name)):
                    det.process(camera, frame, ts, self)
                self.detector_failures.pop(key, None)
            except Exception as exc:
                self.detector_failures[key] = {
                    "camera": camera["id"],
                    "detector": det.name,
                    "error": str(exc),
                    "failed_at": ts,
                }
                log.exception("%s: detector %s failed", camera["name"], det.name)


def resolve_rtsp(cameras):
    """Fill missing rtsp URLs from the Protect bootstrap."""
    missing = [c for c in cameras if not c.get("rtsp")]
    if not missing:
        return cameras
    try:
        client = ProtectClient()
        by_id = {c["id"]: c["rtsp"] for c in client.cameras()}
        by_name = {c["name"]: c["rtsp"] for c in client.cameras()}
        for cam in missing:
            cam["rtsp"] = by_id.get(cam["id"]) or by_name.get(cam["name"]) or cam.get("rtsp")
            if cam["rtsp"]:
                log.info("resolved RTSP for %s", cam["name"])
    except Exception as exc:
        log.warning("Protect discovery failed (%s) — cameras without RTSP are skipped", exc)
    return cameras


def _management_config() -> dict:
    return {
        "site": {"name": "Unconfigured appliance", "timezone": "UTC"},
        "cameras": [],
        "detector_settings": {},
        "alerts": {"dedup_seconds": 120, "severities": {}},
    }


def _load_runtime_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise OSError("missing or oversized configuration")
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (
            not isinstance(config, dict)
            or not isinstance(config.get("site"), dict)
            or not isinstance(config.get("cameras"), list)
            or not isinstance(config.get("detector_settings", {}), dict)
            or not isinstance(config.get("alerts", {}), dict)
        ):
            raise ValueError("invalid configuration shape")
        return config
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        # YAML errors may include source snippets containing local credentials.
        log.error("runtime configuration unavailable; starting management plane only")
        return _management_config()


def _fallback_license_service(detector_classes) -> LicenseService:
    """Return a deny-all verifier when signed-image licensing inputs are broken."""
    return LicenseService(
        directory=os.environ.get("VISION_LICENSE_DIR", "/config/licensing"),
        trusted_keys={},
        catalog_sha256="0" * 64,
        installed_function_tiers={function_id: None for function_id in detector_classes},
    )


def assemble_pipeline(config_path: str | Path) -> Pipeline:
    """Build a fail-closed runtime while preserving the local management plane."""
    config = _load_runtime_config(config_path)
    try:
        detector_classes = load_detectors()
    except Exception:
        log.error("detector registry unavailable; paid analytics remain disabled")
        detector_classes = {}
    try:
        license_service = build_license_service(detector_classes)
    except (LicenseValidationError, OSError, ValueError):
        log.error("licensing inputs unavailable; paid analytics remain disabled")
        license_service = _fallback_license_service(detector_classes)
    try:
        return Pipeline(config, detector_classes, license_service=license_service)
    except Exception:
        log.error("runtime configuration rejected; starting management plane only")
        return Pipeline(_management_config(), {}, license_service=license_service)


def main():
    config_path = os.environ.get("VISION_CONFIG", "/app/config/sites.yaml")
    pipeline = assemble_pipeline(config_path)
    pipeline.cameras = resolve_rtsp(pipeline.cameras)

    frame_interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1.0"))
    streams = StreamManager(
        pipeline.cameras,
        frame_interval,
        pipeline.on_frame,
        on_status=pipeline.on_stream_status,
    )
    streams.start()

    capability_authorizer = (
        pipeline.license_service.allows_capability
        if pipeline.license_service is not None
        else lambda _capability: False
    )
    access = AccessPoller(
        pipeline.on_access_event,
        capability_authorizer=capability_authorizer,
    )
    access.start()
    pipeline.access = access

    protect_events = ProtectEventPoller(
        pipeline.on_protect_event,
        on_poll=pipeline.on_protect_poll,
    )
    protect_events.start()
    pipeline.attach_api_adapters(
        protect_client=protect_events.client,
        access_control=access,
    )
    pipeline.protect_event_poller = protect_events

    # FastAPI status/search server in a side thread
    from api import create_app
    import uvicorn
    app = create_app(pipeline, streams, restart_callback=setup_restart_callback())
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning"),
        daemon=True, name="api",
    )
    server_thread.start()

    log.info("nexus-vision-ai running: %d cameras, detectors=%s",
             len(streams.workers), sorted(pipeline.available_detector_ids))
    try:
        while True:
            time.sleep(30)
            try:
                if pipeline.refresh_license():
                    authorization = pipeline.license_authorization
                    log.warning(
                        "license runtime state changed: state=%s reason=%s active_detectors=%d",
                        getattr(authorization, "state", "invalid"),
                        getattr(authorization, "reason", "unknown"),
                        sum(len(values) for values in pipeline.camera_detectors.values()),
                    )
            except Exception:
                log.exception("license refresh failed")
            try:
                pipeline.alerts.retry_pending()
                pipeline.alerts.prune_storage()
            except Exception:
                log.exception("alert retry or retention maintenance failed")
            try:
                if protect_events.client is not None:
                    inventory_started = time.monotonic()
                    cameras = protect_events.client.cameras()
                    pipeline.on_protect_inventory(
                        cameras,
                        api_latency_ms=(time.monotonic() - inventory_started) * 1000.0,
                    )
            except Exception:
                log.exception("Protect inventory refresh failed")
            dead = [w.camera["name"] for w in streams.workers if not w.connected]
            if dead:
                log.warning("streams down: %s", dead)
    except KeyboardInterrupt:
        pass
    finally:
        streams.stop()
        access.stop()
        protect_events.stop()


if __name__ == "__main__":
    main()
