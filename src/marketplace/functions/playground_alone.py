"""Lone small image-height person signal outside configured windows.

Flags one person detection below a calibrated image-height threshold when no
other person detection is in the zone. It does not determine age or context.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "playground-alone",
    "name": "Lone Small-Figure Playground Alert",
    "tagline": "Flags one person below a calibrated image-height threshold in the playground outside configured windows for staff review; it does not determine age.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — playground/field",
        "recess_windows": "[[start,end],...] hours (default [[9,11],[13,14]])",
        "max_height_ratio": "float — calibrated image-height threshold (default 0.35); not an age estimate",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("recess_windows", [[9, 11], [13, 14]])
        self.max_h = float(self.settings.get("max_height_ratio", 0.35))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("playground")
        if not zone:
            return
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        in_recess = any(int(w[0]) <= hour < int(w[1]) for w in self.windows)
        if in_recess:
            self._since.clear()
            return
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        small_height_detections = [b for b in persons if b[5] - b[3] <= self.max_h]
        key = camera["id"]
        if len(small_height_detections) == 1 and len(persons) == 1:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= 120:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Lone small image-height detection outside configured window",
                    detail=f"One below-threshold person detection remained in the playground zone on {camera['name']} for 2+ minutes; staff review is required.",
                    frame=frame, meta={"minutes": (ts - self._since[key]) / 60})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
