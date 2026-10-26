"""Nap-room motion and sustained-stillness check.

Flags motion during configured nap hours and sustained low motion outside
them. Neither signal establishes occupancy, age, or the reason for motion.
"""
import numpy as np
from marketplace.contract import site_time, MarketplaceFunction

MANIFEST = {
    "id": "nap-room-check",
    "name": "Nap-Room Motion Check",
    "tagline": "Flags motion during configured nap hours or prolonged low motion outside them; staff must inspect the room and calibrate thresholds.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — nap room",
        "nap_hours": "[start,end] (default [12,14])",
        "still_minutes": "int — all-still check after hours (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.nap = self.settings.get("nap_hours", [12, 14])
        self.still_limit = float(self.settings.get("still_minutes", 30)) * 60
        self._prev = {}
        self._still_since = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("nap_room")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        prev = self._prev.get(key)
        self._prev[key] = crop
        if prev is None or prev.shape != crop.shape:
            return
        motion = float(np.mean(cv2.absdiff(crop, prev))) / 255.0
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        nap_now = int(self.nap[0]) <= hour < int(self.nap[1])
        if nap_now and motion > 0.02:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Movement during nap window",
                detail=f"Motion in nap room on {camera['name']} during nap hours.",
                frame=frame, meta={"motion": round(motion, 4)})
        if not nap_now and motion < 0.001:
            self._still_since.setdefault(key, ts)
            if ts - self._still_since[key] >= self.still_limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Sustained low motion outside nap window",
                    detail=f"Low visual motion persisted in the configured nap-room zone for {(ts - self._still_since[key])/60:.0f} min on {camera['name']}; inspect the room.",
                    frame=frame, meta={"still_min": (ts - self._still_since[key]) / 60})
                self._still_since[key] = ts
        else:
            self._still_since.pop(key, None)
