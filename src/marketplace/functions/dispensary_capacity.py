"""Dispensary Capacity — estimated sales-floor occupancy threshold review.

Compares a visual person-count estimate with an operator-configured threshold.
The result is a review prompt, not a legal or licensed-capacity determination.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "dispensary-capacity",
    "name": "Sales Floor Capacity",
    "tagline": "Flags estimated occupancy above the configured licensed-capacity threshold for staff review.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — sales floor",
        "max_persons": "int — operator-configured occupancy review threshold",
        "hold_seconds": "int (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_n = int(self.settings.get("max_persons", 30))
        self.hold = float(self.settings.get("hold_seconds", 30))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("sales_floor")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_n:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Estimated floor count {count} (review threshold {self.max_n})",
                    detail=f"Estimated person count remained above the configured review threshold on {camera['name']} for {ts - self._since[key]:.0f}s; verify the count and applicable capacity rules.",
                    frame=frame, meta={"count": count, "cap": self.max_n})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
