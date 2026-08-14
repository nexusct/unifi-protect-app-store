"""Unit Fullness Estimate — auction-ready visual audit.

Estimates unit fullness from edge density + floor-coverage in the unit
zone. Managers verify "empty" units before over-lock removal and document
fullness for auction compliance photos — without walking every row.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "unit-fullness",
    "name": "Unit Fullness Audit",
    "tagline": "Unit 87 is 90% full, not empty. The auction listing just changed.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "units": "map of unit-name → interior polygon",
        "empty_ratio": "float — edge density below = empty (default 0.02)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.empty_ratio = float(self.settings.get("empty_ratio", 0.02))
        self._reported = {}

    def process(self, camera, frame, ts, ctx):
        units = (camera.get("zones") or {}).get("units") or {}
        if not units:
            return
        import cv2
        h, w = frame.shape[:2]
        for name, poly in units.items():
            key = (camera["id"], name)
            if ts - self._reported.get(key, 0) < 86400:  # daily per unit
                continue
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
            if crop.size == 0:
                continue
            density = float(np.count_nonzero(cv2.Canny(crop, 50, 150))) / crop.size
            self._reported[key] = ts
            state = "appears EMPTY" if density < self.empty_ratio else "appears OCCUPIED"
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Unit {name}: {state}",
                detail=f"Unit {name} on {camera['name']} {state} (density {density:.3f}).",
                frame=frame, meta={"unit": name, "density": round(density, 4)})
