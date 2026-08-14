"""Splash Pad Capacity — bather count vs posted limit.

Counts persons in the splash-pad zone against the posted bather load.
Park districts carry the liability; this carries the count.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "splash-pad-capacity",
    "name": "Splash Pad Capacity",
    "tagline": "Posted limit 40. Count is 52. The alert went to the field supervisor.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — splash pad",
        "max_persons": "int (default 40)",
        "hold_seconds": "int (default 60)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_n = int(self.settings.get("max_persons", 40))
        self.hold = float(self.settings.get("hold_seconds", 60))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pad")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_n:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Splash pad at {count} (limit {self.max_n})",
                    detail=f"Bather count over posted limit on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"count": count})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
