"""Classroom image-height grouping ratio estimate.

Groups person detections above and below a calibrated image-height threshold.
The groups are not age or staff classifications and require manual review.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "daycare-ratio",
    "name": "Classroom Ratio Estimate",
    "tagline": "Compares smaller and larger image-height person-detection groups for staff review; it does not classify age or replace required headcounts.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — classroom",
        "max_ratio": "float — smaller-to-larger image-height group ratio (default 8)",
        "child_height_ratio": "Camera-specific image-height split used only for visual grouping; it does not determine age.",
        "hold_seconds": "int (default 120)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_ratio = float(self.settings.get("max_ratio", 8))
        self.child_h = float(self.settings.get("child_height_ratio", 0.38))
        self.hold = float(self.settings.get("hold_seconds", 120))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("classroom")
        if not zone:
            return
        smaller = larger = 0
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if not in_zone(cx, cy, zone):
                continue
            if y2 - y1 <= self.child_h:
                smaller += 1
            else:
                larger += 1
        key = camera["id"]
        ratio = smaller / max(larger, 1) if smaller else 0
        if smaller and ratio > self.max_ratio:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Image-height group ratio {ratio:.1f}:1",
                    detail=f"{smaller} smaller-height and {larger} larger-height person detections on {camera['name']} persisted for {ts - self._since[key]:.0f}s; verify classroom counts manually.",
                    frame=frame, meta={"smaller_height": smaller, "larger_height": larger, "ratio": round(ratio, 1)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
