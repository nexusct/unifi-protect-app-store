"""Small image-height person detection in a restricted area.

Flags person detections below a camera-calibrated bounding-box height. The
proxy does not determine age, identity, or authorization.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "child-safety-zone",
    "name": "Small-Person Restricted-Zone Alert",
    "tagline": "Flags a person detection below a calibrated image-height threshold in a restricted zone for immediate human review; it does not determine age.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — restricted area",
        "max_height_ratio": "float — calibrated image-height threshold (default 0.35); not an age estimate",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_h = float(self.settings.get("max_height_ratio", 0.35))
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("restricted")
        if not zone:
            return
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            height_ratio = y2 - y1
            if height_ratio <= self.max_h and ts - self._alerted.get(tid, 0) > 120:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Small image-height person detection in restricted zone",
                    detail=f"Person bounding-box height ratio {height_ratio:.2f} was below the configured threshold in the restricted zone on {camera['name']}; review required.",
                    frame=frame, meta={"height_ratio": round(height_ratio, 3)})
