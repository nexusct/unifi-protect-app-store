"""Detector 10: smoke/flame visual detection (before sensors trip).

Domain weights recommended (detector_settings.smoke_flame.weights with
smoke/fire classes). Without them, a heuristic fallback watches for
fast-growing bright warm-color regions in the upper frame — crude but
better than nothing in tall-ceiling spaces; expect false positives and
tune per camera.
"""
import logging

import numpy as np

from detectors.base import Detector, get_model, register

log = logging.getLogger("detectors.smoke_flame")


@register
class SmokeFlameDetector(Detector):
    name = "smoke_flame"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("weights", "/app/models/smoke.pt")
        self.conf = float(self.settings.get("confidence", 0.50))
        self._model = None
        self._warm_history = {}

    def _custom_model(self, camera, frame, ts, ctx) -> bool:
        if self._model is None:
            self._model = get_model(self.weights)
        res = self._model(frame, verbose=False, conf=self.conf)[0]
        names = {k: str(v).lower() for k, v in (res.names or {}).items()}
        for box in res.boxes or []:
            cls = names.get(int(box.cls[0]), "")
            if cls in ("smoke", "fire", "flame"):
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=self.name,
                    title=f"{cls.title()} detected",
                    detail=f"Visual {cls} at {float(box.conf[0]):.0%} on {camera['name']} — before sensor thresholds.",
                    frame=frame,
                    meta={"class": cls, "confidence": float(box.conf[0])},
                )
                return True
        return False

    def _heuristic(self, camera, frame, ts, ctx):
        """Fallback: fast-growing warm bright region in upper half of frame."""
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        upper = hsv[: frame.shape[0] // 2]
        # warm hue band + bright + moderately saturated
        mask = cv2.inRange(upper, (0, 60, 200), (35, 255, 255))
        ratio = float(np.count_nonzero(mask)) / mask.size
        hist = self._warm_history.setdefault(camera["id"], [])
        hist.append((ts, ratio))
        self._warm_history[camera["id"]] = hist[-15:]
        if len(hist) >= 10:
            growth = ratio - min(r for _, r in hist[:-5])
            if ratio > 0.02 and growth > 0.01:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=self.name,
                    title="Possible flame signature (heuristic)",
                    detail=f"Fast-growing warm region on {camera['name']} (ratio {ratio:.3f}). Verify visually.",
                    frame=frame,
                    meta={"ratio": ratio, "growth": growth, "mode": "heuristic"},
                )
                self._warm_history[camera["id"]] = []

    def process(self, camera, frame, ts, ctx):
        import os
        if os.path.exists(self.weights):
            self._custom_model(camera, frame, ts, ctx)
        else:
            self._heuristic(camera, frame, ts, ctx)
