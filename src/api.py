"""FastAPI: health, stream status, detector status, NL video search."""
from fastapi import FastAPI, Query


def create_app(pipeline, streams):
    app = FastAPI(title="nexus-vision-ai", version="0.1.0")

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
