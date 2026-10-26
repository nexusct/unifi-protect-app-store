"""Clinical-Attire Color Check — torso color-signature review.

Checks the torso region for an operator-configured light-color signature in a
clinical zone. It cannot determine role, authorization, attire type, or compliance.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone, pixel_box

MANIFEST = {
    "id": "lab-coat-zone",
    "name": "Clinical-Attire Color Check",
    "tagline": "Flags people whose torso region lacks the configured clinical-attire color signature; human review required.",
    "category": "Healthcare & Senior Living",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — clinical corridor",
        "clinical_hue": "[low,high] HSV band for scrubs/whites (default [0,180] low-sat high-val = white)",
        "min_ratio": "float (default 0.2)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        hue = self.settings.get("clinical_hue", [0, 180])
        self.lo, self.hi = int(hue[0]), int(hue[1])
        self.min_ratio = float(self.settings.get("min_ratio", 0.2))
        self._flagged = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("clinical")
        if not zone:
            return
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone) or ts - self._flagged.get(tid, 0) < 300:
                continue
            px1, py1, px2, py2 = pixel_box(frame, x1, y1, x2, y2)
            ty1 = int(py1 + (py2 - py1) * 0.3)
            ty2 = int(py1 + (py2 - py1) * 0.7)
            torso = hsv[ty1:ty2, px1:px2]
            if torso.size == 0:
                continue
            # white/light clinical wear: high value, low saturation
            mask = cv2.inRange(torso, (self.lo, 0, 170), (self.hi, 60, 255))
            ratio = float(np.count_nonzero(mask)) / mask.size
            if ratio < self.min_ratio:
                self._flagged[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Configured attire color signature not observed",
                    detail=f"Torso-region light-color ratio was {ratio:.2f} on {camera['name']}, below the configured review threshold; verify attire and authorization manually.",
                    frame=frame, meta={"ratio": round(ratio, 3)})
