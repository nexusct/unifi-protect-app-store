"""Hangar Door State — door open after hours.

Hangar door zone state vs the closed reference, after-hours only. Open
hangars at night are weather, security, and insurance exposure.
"""
import numpy as np
from marketplace.contract import site_time, MarketplaceFunction

MANIFEST = {
    "id": "hangar-door-state",
    "name": "Hangar Door After-Hours",
    "tagline": "Flags a persistent visual open-state at a configured hangar-door zone during selected hours.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — door face",
        "after_hours": "[start,end] (default [19,7])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("after_hours", [19, 7])
        self._closed = {}
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("door")
        if not zone:
            return
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        s, e = int(self.hours[0]), int(self.hours[1])
        if not ((hour >= s or hour < e) if s > e else (s <= hour < e)):
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        ref = self._closed.get(key)
        if ref is None or ref.shape != crop.shape:
            self._closed[key] = crop
            return
        diff = float(np.mean(cv2.absdiff(crop, ref))) / 255.0
        if diff > 0.08 and ts - self._alerted.get(key, 0) > 1800:
            self._alerted[key] = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Hangar door open after hours",
                detail=f"Door state differs from closed reference on {camera['name']}.",
                frame=frame, meta={"diff": round(diff, 3)})
