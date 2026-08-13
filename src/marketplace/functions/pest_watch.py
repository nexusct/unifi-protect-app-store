"""Pest Watch — small fast movers at floor level, after hours.

Detects small, fast, low-profile motion blobs in kitchen/storage zones
during closed hours — the rodent signature. Food-service operators get
the alert days before the health inspector or a Yelp photo finds it.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "pest-watch",
    "name": "Pest Watch (After-Hours)",
    "tagline": "Small, fast, floor-level, 2am. You want to know.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — kitchen/storage floor",
        "active_hours": "[start,end] — closed hours (default [22,5])",
        "min_speed": "float — blob speed proxy (default 0.02 norm/frame)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("active_hours", [22, 5])
        self.min_speed = float(self.settings.get("min_speed", 0.02))
        self._prev = {}
        self._prev_pos = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        import cv2
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        start, end = int(self.hours[0]), int(self.hours[1])
        active = (hour >= start or hour < end) if start > end else (start <= hour < end)
        if not active:
            return
        zone = (camera.get("zones") or {}).get("floor")
        if not zone:
            return
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        x1, x2 = int(min(xs)*w), int(max(xs)*w)
        y1, y2 = int(min(ys)*h), int(max(ys)*h)
        gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        key = camera["id"]
        prev = self._prev.get(key)
        self._prev[key] = gray
        if prev is None or prev.shape != gray.shape:
            return
        diff = cv2.threshold(cv2.absdiff(gray, prev), 25, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if not (20 <= area <= 2000):  # small-blob band: not a person, not noise
                continue
            bx, by, bw, bh = cv2.boundingRect(c)
            cx, cy = (bx + bw / 2) / gray.shape[1], (by + bh / 2) / gray.shape[0]
            prev_pos = self._prev_pos.get(key)
            self._prev_pos[key] = (cx, cy)
            if prev_pos and ((cx - prev_pos[0]) ** 2 + (cy - prev_pos[1]) ** 2) ** 0.5 >= self.min_speed:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Small fast mover at floor level",
                    detail=f"Pest-signature motion on {camera['name']} during closed hours.",
                    frame=frame, meta={"blob_area": int(area)})
                break
