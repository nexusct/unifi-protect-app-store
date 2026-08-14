"""Visitor Badge Check — floor presence without the badge color patch.

Dispensary/back-office visitor compliance: person in the controlled zone
whose chest region lacks the badge/lanyard color signature. Regulated
facilities get cited for unbadged visitors — this produces the patrol.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "visitor-badge-check",
    "name": "Visitor Badge Check",
    "tagline": "No badge patch on the sales floor. Flagged in real time.",
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
            py1, py2 = int(y1 + (y2 - y1) * 0.15), int(y1 + (y2 - y1) * 0.45)
            px1, px2 = int(x1 + (x2 - x1) * 0.3), int(x1 + (x2 - x1) * 0.7)
            patch = hsv[py1:py2, px1:px2]
            if patch.size == 0:
                continue
            mask = cv2.inRange(patch, (self.lo, 80, 80), (self.hi, 255, 255))
            ratio = float(np.count_nonzero(mask)) / mask.size
            if ratio < self.min_ratio:
                self._flagged[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Unbadged person in controlled zone",
                    detail=f"Person lacks badge color signature on {camera['name']} (ratio {ratio:.3f}).",
                    frame=frame, meta={"ratio": round(ratio, 4)})
