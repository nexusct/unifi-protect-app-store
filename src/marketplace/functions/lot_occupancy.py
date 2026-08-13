"""Lot Occupancy — live parking count vs capacity.

Vehicles counted in the lot zone vs configured capacity. Emits occupancy
percentages and lot-full alerts — tenant/visitor guidance, event staffing,
and the data behind "we don't need more parking" (or "we do").
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "lot-occupancy",
    "name": "Parking Lot Occupancy",
    "tagline": "Live lot count. Full-lot alerts. Zero sensors in the pavement.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — lot area",
        "capacity": "int — total spaces",
        "full_ratio": "float — alert at this fill (default 0.95)",
    },
}

VEHICLES = (2, 3, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.capacity = int(self.settings.get("capacity", 50))
        self.full = float(self.settings.get("full_ratio", 0.95))
        self._was_full = False

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("lot")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=list(VEHICLES)) if in_zone(cx, cy, zone))
        ratio = count / max(self.capacity, 1)
        if ratio >= self.full and not self._was_full:
            self._was_full = True
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Lot at {ratio:.0%} capacity",
                detail=f"{count}/{self.capacity} vehicles on {camera['name']}.",
                frame=frame, meta={"count": count, "capacity": self.capacity})
        elif ratio < self.full - 0.1:
            self._was_full = False
