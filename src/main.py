"""Nexus Vision AI entrypoint: config → streams → detectors → alerts → API."""
import logging
import os
import threading
import time
from collections import deque

import yaml

from alerts import AlertEngine
from detectors.base import DETECTOR_REGISTRY
from streams import StreamManager
from unifi_access import AccessPoller
from unifi_protect import ProtectClient

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


class Pipeline:
    def __init__(self, config: dict):
        self.config = config
        self.site = config.get("site", {}).get("name", "site")
        self.alerts = AlertEngine(config, os.environ.get("VISION_DATA", "/app/data"))
        self.access_events = deque(maxlen=500)
        self.cameras = config.get("cameras", [])
        self.settings = config.get("detector_settings", {})

        # Per-camera detector instances
        self.camera_detectors = {}
        for cam in self.cameras:
            instances = []
            for det_name in cam.get("detectors", []):
                cls = DETECTOR_REGISTRY.get(det_name)
                if not cls:
                    log.error("unknown detector %s on %s", det_name, cam.get("name"))
                    continue
                cam_settings = dict(self.settings.get(det_name, {}))
                cam_settings.update(cam.get(det_name, {}))
                instances.append(cls(cam_settings))
            self.camera_detectors[cam["id"]] = instances

    def on_access_event(self, event: dict):
        self.access_events.append(event)

    def on_frame(self, camera: dict, frame, ts: float):
        # Privacy: skeleton mode discards frames after pose extraction —
        # detectors receive the frame but snapshots are suppressed upstream.
        for det in self.camera_detectors.get(camera["id"], []):
            det.process(camera, frame, ts, self)


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


def main():
    config_path = os.environ.get("VISION_CONFIG", "/app/config/sites.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    load_detectors()
    pipeline = Pipeline(config)
    pipeline.cameras = resolve_rtsp(pipeline.cameras)

    frame_interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1.0"))
    streams = StreamManager(pipeline.cameras, frame_interval, pipeline.on_frame)
    streams.start()

    access = AccessPoller(pipeline.on_access_event)
    access.start()
    pipeline.access = access

    # FastAPI status/search server in a side thread
    from api import create_app
    import uvicorn
    app = create_app(pipeline, streams)
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning"),
        daemon=True, name="api",
    )
    server_thread.start()

    log.info("nexus-vision-ai running: %d cameras, detectors=%s",
             len(streams.workers), sorted(DETECTOR_REGISTRY.keys()))
    try:
        while True:
            time.sleep(30)
            dead = [w.camera["name"] for w in streams.workers if not w.connected]
            if dead:
                log.warning("streams down: %s", dead)
    except KeyboardInterrupt:
        pass
    finally:
        streams.stop()
        access.stop()


if __name__ == "__main__":
    main()
