"""RTSP stream manager: one worker per camera, shared frame bus."""
import logging
import threading
import time

import cv2

log = logging.getLogger("streams")


class StreamWorker(threading.Thread):
    """Reads a camera RTSP stream, throttles to frame_interval, and hands
    frames to the detector pipeline. Reconnects with backoff on drops."""

    def __init__(self, camera: dict, frame_interval: float, on_frame):
        super().__init__(daemon=True, name=f"stream-{camera['name']}")
        self.camera = camera
        self.frame_interval = frame_interval
        self.on_frame = on_frame
        self._stop = threading.Event()
        self.frames_read = 0
        self.last_frame_at = None
        self.connected = False

    def run(self):
        backoff = 1
        while not self._stop.is_set():
            url = self.camera.get("rtsp")
            if not url:
                log.error("%s: no RTSP url — skipping", self.camera["name"])
                return
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                log.warning("%s: connect failed, retry in %ss", self.camera["name"], backoff)
                self.connected = False
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = 1
            self.connected = True
            log.info("%s: stream connected", self.camera["name"])
            last_emit = 0.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    log.warning("%s: frame read failed — reconnecting", self.camera["name"])
                    self.connected = False
                    break
                now = time.time()
                if now - last_emit >= self.frame_interval:
                    last_emit = now
                    self.frames_read += 1
                    self.last_frame_at = now
                    try:
                        self.on_frame(self.camera, frame, now)
                    except Exception:
                        log.exception("%s: detector error", self.camera["name"])
            cap.release()

    def stop(self):
        self._stop.set()

    def status(self):
        return {
            "camera": self.camera["name"],
            "connected": self.connected,
            "frames_read": self.frames_read,
            "last_frame_at": self.last_frame_at,
        }


class StreamManager:
    def __init__(self, cameras, frame_interval, on_frame):
        self.workers = [StreamWorker(c, frame_interval, on_frame) for c in cameras if c.get("rtsp")]

    def start(self):
        for w in self.workers:
            w.start()

    def stop(self):
        for w in self.workers:
            w.stop()

    def status(self):
        return [w.status() for w in self.workers]
