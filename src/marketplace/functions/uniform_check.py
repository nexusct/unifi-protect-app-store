"""Uniform Check — staff-zone presence without the uniform color signature.

Samples torso-region hue of each person in a staff-only zone and compares
against the configured uniform color band. Mismatches = contractor/visitor
in staff area or dress-code gap, flagged with the frame.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "uniform-check",
    "name": "Uniform Compliance Check",
    "tagline": "Who's on the floor without the uniform? The camera knows.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — staff-only area",
        "uniform_hue": "[low, high] HSV hue band (default [90, 130] = blue scrubs)",
        "min_ratio": "float — min uniform pixels (default 0.25)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        hue = self.settings.get("uniform_hue", [90, 130])
        self.lo, self.hi = int(hue[0]), int(hue[1])
        self.min_ratio = float(self.settings.get("min_ratio", 0.25))
        self._flagged = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("staff_area")
        if not zone:
            return
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            if ts - self._flagged.get(tid, 0) < 300:
                continue
            # torso band: middle 40% of the bbox
            ty1, ty2 = int(y1 + (y2 - y1) * 0.3), int(y1 + (y2 - y1) * 0.7)
            torso = hsv[ty1:ty2, int(x1):int(x2)]
            if torso.size == 0:
                continue
            mask = cv2.inRange(torso, (self.lo, 40, 40), (self.hi, 255, 255))
            ratio = float(np.count_nonzero(mask)) / mask.size
            if ratio < self.min_ratio:
                self._flagged[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Uniform mismatch in staff area",
                    detail=f"Person on {camera['name']} lacks the uniform color signature (ratio {ratio:.2f}).",
                    frame=frame, meta={"track": tid, "ratio": round(ratio, 3)})
