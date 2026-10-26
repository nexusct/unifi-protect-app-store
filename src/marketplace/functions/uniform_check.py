"""Uniform Color-Signature Check — configured torso-color proxy.

Samples torso-region hue for person-class detections in a configured zone and
flags ratios below an operator-selected color threshold. It does not determine
role, attire type, authorization, or compliance.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone, pixel_box

MANIFEST = {
    "id": "uniform-check",
    "name": "Uniform Color-Signature Check",
    "tagline": "Flags people whose torso region lacks a calibrated uniform-color signature for human review.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — staff-only area",
        "uniform_hue": "[low, high] configured HSV hue band (default [90, 130])",
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
            # torso band: middle 40% of the normalized bbox, converted for slicing
            px1, py1, px2, py2 = pixel_box(frame, x1, y1, x2, y2)
            ty1 = int(py1 + (py2 - py1) * 0.3)
            ty2 = int(py1 + (py2 - py1) * 0.7)
            torso = hsv[ty1:ty2, px1:px2]
            if torso.size == 0:
                continue
            mask = cv2.inRange(torso, (self.lo, 40, 40), (self.hi, 255, 255))
            ratio = float(np.count_nonzero(mask)) / mask.size
            if ratio < self.min_ratio:
                self._flagged[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Configured torso color signature not observed",
                    detail=f"Torso-region color ratio {ratio:.2f} was below the configured threshold on {camera['name']}; review attire and authorization manually.",
                    frame=frame, meta={"track": tid, "ratio": round(ratio, 3)})
