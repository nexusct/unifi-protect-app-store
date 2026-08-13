"""Lighting Outage — dark-zone detection on a schedule.

Mean luma in a zone drops below threshold during scheduled-lit hours =
parking-lot light out / corridor dark. Liability loves dark stairwells;
this finds them before the incident report does.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "lighting-outage",
    "name": "Lighting Outage Watch",
    "tagline": "The parking lot light that's been out for a week? Found in a day.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — lit area (optional: whole frame)",
        "min_luma": "float 0-255 (default 40)",
        "lit_hours": "[start,end] hours 0-23 (default [18,6] = overnight)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.min_luma = float(self.settings.get("min_luma", 40))
        self.lit = self.settings.get("lit_hours", [18, 6])
        self._dark_since = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        import cv2
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        start, end = self.lit
        lit_now = (hour >= start or hour < end) if start > end else (start <= hour < end)
        if not lit_now:
            self._dark_since.pop(camera["id"], None)
            return
        zone = (camera.get("zones") or {}).get("lit_area")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if zone:
            h, w = gray.shape
            xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
            gray = gray[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)]
        luma = float(np.mean(gray)) if gray.size else 255.0
        key = camera["id"]
        if luma < self.min_luma:
            self._dark_since.setdefault(key, ts)
            if ts - self._dark_since[key] >= 120:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Area dark during lit hours",
                    detail=f"Mean luma {luma:.0f} on {camera['name']} — possible lighting outage.",
                    frame=frame, meta={"luma": round(luma, 1)})
                self._dark_since[key] = ts
        else:
            self._dark_since.pop(key, None)
