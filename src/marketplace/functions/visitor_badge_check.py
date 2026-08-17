"""Configured badge-color signature check.

Flags when the configured color signature is not observed in an upper-body
crop. The heuristic does not determine badge, visitor, or authorization status.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone, pixel_box

MANIFEST = {
    "id": "visitor-badge-check",
    "name": "Badge Color-Signature Check",
    "tagline": "Flags people whose upper-body region lacks a calibrated badge-color signature; verify detections and delivery latency during commissioning.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — controlled floor",
        "badge_hue": "[low,high] HSV badge color band (default [0,10] = red)",
        "min_ratio": "float (default 0.02)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        hue = self.settings.get("badge_hue", [0, 10])
        self.lo, self.hi = int(hue[0]), int(hue[1])
        self.min_ratio = float(self.settings.get("min_ratio", 0.02))
        self._flagged = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("floor")
        if not zone:
            return
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone) or ts - self._flagged.get(tid, 0) < 300:
                continue
            # chest patch: upper third of bbox, center half width
            bx1, by1, bx2, by2 = pixel_box(frame, x1, y1, x2, y2)
            py1 = int(by1 + (by2 - by1) * 0.15)
            py2 = int(by1 + (by2 - by1) * 0.45)
            px1 = int(bx1 + (bx2 - bx1) * 0.3)
            px2 = int(bx1 + (bx2 - bx1) * 0.7)
            patch = hsv[py1:py2, px1:px2]
            if patch.size == 0:
                continue
            mask = cv2.inRange(patch, (self.lo, 80, 80), (self.hi, 255, 255))
            ratio = float(np.count_nonzero(mask)) / mask.size
            if ratio < self.min_ratio:
                self._flagged[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Badge-color signature not observed",
                    detail=f"Configured color coverage measured {ratio:.3f} in the upper-body crop on {camera['name']}; verify badge status manually.",
                    frame=frame, meta={"ratio": round(ratio, 4)})
