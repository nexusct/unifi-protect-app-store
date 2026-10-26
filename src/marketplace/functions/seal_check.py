"""Seal Check — trailer door opened at an unapproved location.

Watches the trailer-rear zone: door-open visual state (dark gap / swing
door pixels change) at the dock is expected; the same signature in a
parking row zone = possible pilferage check.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "seal-check",
    "name": "Trailer Rear-State Change",
    "tagline": "Flags a sustained visual change in a configured trailer-rear zone for review; it does not determine door state, seal status, or pilferage.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — trailer rear area in parking row",
        "diff_ratio": "float (default 0.15)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.diff_limit = float(self.settings.get("diff_ratio", 0.15))
        self._ref = {}
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("trailer_rear")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        ref = self._ref.get(key)
        if ref is None or ref.shape != crop.shape:
            self._ref[key] = crop
            return
        diff = float(np.mean(cv2.absdiff(crop, ref))) / 255.0
        if diff >= self.diff_limit:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= 30:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Trailer rear opened in row",
                    detail=f"Rear-door state change on {camera['name']} outside the dock zone.",
                    frame=frame, meta={"diff": round(diff, 3)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
            # slow-adapt reference so the parked trailer itself becomes baseline
            self._ref[key] = cv2.addWeighted(ref, 0.98, crop, 0.02, 0)
