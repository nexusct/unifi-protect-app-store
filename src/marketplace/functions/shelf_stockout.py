"""Shelf Stockout — empty-shelf detection from edge-density drop.

A stocked shelf has high edge/texture density; an empty one goes flat.
Compares the shelf zone's edge density to a learned stocked baseline and
alerts when it drops past the threshold — the difference between a
restock at 2pm and a lost sale all afternoon.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "shelf-stockout",
    "name": "Shelf Stockout Alert",
    "tagline": "Empty shelf at 2pm = lost sales all afternoon.",
    "category": "Retail & QSR",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — shelf area",
        "drop_ratio": "float — density drop vs baseline (default 0.35)",
        "learn_frames": "int — baseline frames to average (default 50)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.drop = float(self.settings.get("drop_ratio", 0.35))
        self.learn = int(self.settings.get("learn_frames", 50))
        self._baseline = {}
        self._samples = {}

    @staticmethod
    def _density(frame, zone, shape):
        import cv2
        h, w = shape
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        x1, x2 = int(min(xs) * w), int(max(xs) * w)
        y1, y2 = int(min(ys) * h), int(max(ys) * h)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return 0.0
        edges = cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 60, 160)
        return float(np.count_nonzero(edges)) / edges.size

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("shelf")
        if not zone:
            return
        key = camera["id"]
        d = self._density(frame, zone, frame.shape[:2])
        if key not in self._baseline:
            self._samples.setdefault(key, []).append(d)
            if len(self._samples[key]) >= self.learn:
                self._baseline[key] = float(np.mean(self._samples[key]))
            return
        base = self._baseline[key]
        if base > 0 and (base - d) / base >= self.drop:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Shelf looks empty",
                detail=f"Edge density dropped {(base - d) / base:.0%} vs stocked baseline on {camera['name']}.",
                frame=frame, meta={"baseline": base, "current": d})
