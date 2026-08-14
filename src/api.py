"""FastAPI: health, stream status, detector status, NL video search,
subscription signup API, landing page + storefront static mounts."""
import os
from pathlib import Path

from fastapi import FastAPI, Query, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

ROOT = Path("/app")
LANDING = ROOT / "landing"
STOREFRONT = ROOT / "storefront"
GUIDE = ROOT / "guide"

# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)


def create_app(pipeline, streams):
    app = FastAPI(title="nexus-vision-ai", version="0.2.0")
    
    # Register rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── subscription platform + storefront ──
    from subscriptions import store
    from subscriptions.app import router as sub_router
    from subscriptions.app import limiter as sub_limiter
    store.init_db()
    app.include_router(sub_router)
    # Register subscription router's limiter
    app.state.limiter = sub_limiter
    if LANDING.exists():
        app.mount("/assets", StaticFiles(directory=str(LANDING / "assets")), name="landing-assets")

        @app.get("/", include_in_schema=False)
        def landing():
            return FileResponse(str(LANDING / "index.html"))

    if STOREFRONT.exists():
        app.mount("/storefront", StaticFiles(directory=str(STOREFRONT), html=True), name="storefront")
    if GUIDE.exists():
        app.mount("/guide", StaticFiles(directory=str(GUIDE), html=True), name="guide")

    @app.get("/health")
    def health():
        up = sum(1 for w in streams.workers if w.connected)
        return {
            "ok": True,
            "site": pipeline.site,
            "streams_up": up,
            "streams_total": len(streams.workers),
            "alerts": pipeline.alerts.stats(),
        }

    @app.get("/streams")
    def stream_status():
        return streams.status()

    @app.get("/detectors")
    def detector_status():
        return {
            cam: [d.name for d in dets]
            for cam, dets in pipeline.camera_detectors.items()
        }

    @app.get("/search")
    @limiter.limit("30/minute")
    def search(request: Request, q: str = Query(..., min_length=2), limit: int = 10):
        """Natural language video search.
        
        Rate limit: 30 requests per minute per IP to prevent resource exhaustion.
        """
        from detectors.video_search import search as vs_search
        return {"query": q, "results": vs_search(q, limit=limit)}

    @app.post("/unlock/{door_id}")
    @limiter.limit("5/minute")
    def unlock_door(request: Request, door_id: str, x_admin_token: str | None = Header(default=None)):
        """Remote door unlock (requires admin token).
        
        Security: This endpoint can trigger physical door unlocks and must be
        protected. Use network-level access control (firewall, reverse proxy)
        in addition to token authentication.
        
        Rate limit: 5 requests per minute per IP to prevent brute-force attacks
        and unauthorized unlock attempts.
        """
        expected = os.environ.get("VISION_ADMIN_TOKEN", "")
        if not expected or len(expected) < 16 or "change-me" in expected.lower():
            raise HTTPException(503, "admin token not configured or insecure (must be 16+ chars, not 'change-me')")
        if not x_admin_token or x_admin_token != expected:
            raise HTTPException(401, "invalid admin token")
        ok = pipeline.access.unlock(door_id) if getattr(pipeline, "access", None) else False
        return {"door_id": door_id, "unlocked": ok}

    return app
