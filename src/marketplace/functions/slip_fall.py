"""Slip & Fall (public liability) — fall detection + instant clip retention.

Same torso-angle core as resident fall detection, tuned for public areas:
the product is the preserved clip. Liability defense lives or dies on
whether footage was kept — this fires the alert AND the clip in one move.
"""
import time
from marketplace.contract import MarketplaceFunction, model

MANIFEST = {
    "id": "slip-fall",
    "name": "Slip & Fall Liability Guard",
    "tagline": "Someone fell. The clip is already saved.",
    "category": "Property & Liability",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "confidence": "float (default 0.55)",
        "floor_angle_seconds": "float (default 1.5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.conf = float(self.settings.get("confidence", 0.55))
        self.hold = float(self.settings.get("floor_angle_seconds", 1.5))
        self._since = {}
        self._model = None

    def process(self, camera, frame, ts, ctx):
        if self._model is None:
            import os
            self._model = model("yolov8n-pose.pt", os.environ.get("VISION_DEVICE", "cuda"))
        res = self._model(frame, verbose=False, conf=self.conf)[0]
        import math
        horizontal = False
        if res.keypoints is not None and len(res.keypoints.xy):
            for kps in res.keypoints.data.cpu().numpy():
                ls, rs, lh, rh = kps[5], kps[6], kps[11], kps[12]
                if min(ls[2], rs[2], lh[2], rh[2]) < 0.3:
                    continue
                dx = abs((ls[0] + rs[0]) / 2 - (lh[0] + rh[0]) / 2)
                dy = abs((ls[1] + rs[1]) / 2 - (lh[1] + rh[1]) / 2)
                if dx + dy > 1e-3 and math.degrees(math.atan2(dx, dy)) > 60:
                    horizontal = True
                    break
        key = camera["id"]
        if horizontal:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Person down in public area",
                    detail=f"Fall signature held {ts - self._since[key]:.1f}s on {camera['name']}. Clip preserved.",
                    frame=frame, meta={"held": ts - self._since[key], "retain_clip": True})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
