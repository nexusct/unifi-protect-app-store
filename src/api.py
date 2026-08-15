"""FastAPI: health, stream status, detector status, NL video search,
subscription signup API, landing page + storefront static mounts."""
import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path("/app")
LANDING = ROOT / "landing"
STOREFRONT = ROOT / "storefront"
GUIDE = ROOT / "guide"
ASSETS = ROOT / "assets"


def create_app(pipeline, streams):
    app = FastAPI(title="nexus-vision-ai", version="0.2.0")

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
    def search(q: str = Query(..., min_length=2), limit: int = 10):
        from detectors.video_search import search as vs_search
        return {"query": q, "results": vs_search(q, limit=limit)}

    @app.post("/unlock/{door_id}")
    def unlock_door(door_id: str):
        ok = pipeline.access.unlock(door_id) if getattr(pipeline, "access", None) else False
        return {"door_id": door_id, "unlocked": ok}

    return app
