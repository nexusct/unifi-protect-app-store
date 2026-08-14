"""Dispensary Capacity — sales-floor occupancy vs licensed cap.

Live person count on the sales floor against the license/fire capacity.
Over-cap = door staff alert. License caps are enforced in regulated retail;
this makes the count continuous and documented.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "dispensary-capacity",
    "name": "Sales Floor Capacity",
    "tagline": "Licensed cap is 30. You're at 34. The door got the alert, not the inspector.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — sales floor",
        "max_persons": "int — licensed cap",
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
                    title=f"Floor at {count} (cap {self.max_n})",
                    detail=f"Sales floor over licensed cap on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"count": count, "cap": self.max_n})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
