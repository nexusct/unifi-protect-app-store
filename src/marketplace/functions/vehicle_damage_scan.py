"""Vehicle Damage Scan — per-stall daily diff for dealerships/rental.

Each stall's vehicle is compared day-over-day; a significant structural
change flags possible new damage. Lot-liability disputes ("it was already
scratched") end with dated frame pairs.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "vehicle-damage-scan",
    "name": "Vehicle Damage Scan",
    "tagline": "New scratch on a lot vehicle? Dated before/after frames settle it.",
    "category": "Automotive & Parking",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "stalls": "map of stall-name → polygon",
        "diff_ratio": "float — change threshold (default 0.12)",
        "scan_hour": "int — daily scan hour (default 7)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.diff_limit = float(self.settings.get("diff_ratio", 0.12))
        self.scan_hour = int(self.settings.get("scan_hour", 7))
        self._ref = {}
        self._last_day = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        import cv2
        stalls = (camera.get("zones") or {}).get("stalls") or {}
        if not stalls:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        day = _t.strftime("%Y-%m-%d", _t.gmtime(ts))
        if hour != self.scan_hour:
            return
        h, w = frame.shape[:2]
        for name, poly in stalls.items():
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
            if crop.size == 0:
                continue
            key = (camera["id"], name)
            if self._last_day.get(key) == day:
                continue
            ref = self._ref.get(key)
            self._ref[key] = crop
            self._last_day[key] = day
            if ref is None or ref.shape != crop.shape:
                continue
            diff = float(np.mean(cv2.absdiff(crop, ref))) / 255.0
            if diff >= self.diff_limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Possible new damage: stall {name}",
                    detail=f"Day-over-day change {diff:.0%} in stall {name} on {camera['name']}.",
                    frame=frame, meta={"stall": name, "diff": round(diff, 3)})
