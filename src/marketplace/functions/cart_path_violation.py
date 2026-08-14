"""Cart Path Violation — cart off the path zone on cart-path-only days.

Course-protect mode: cart detected in turf/fairway zones when the course
is path-only. Turf repair and member friction both drop when enforcement
is consistent and documented.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "cart-path-violation",
    "name": "Cart Path Violation",
    "tagline": "Cart-path-only day. Cart on the fairway at 14. Photo attached.",
    "category": "Compliance",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — protected turf area",
        "active": "bool — enable on path-only days",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        if not self.settings.get("active", True):
            return
        zone = (camera.get("zones") or {}).get("protected_turf")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            if ts - self._alerted.get(tid, 0) > 300:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Cart off path on protected turf",
                    detail=f"Cart in protected turf zone on {camera['name']}.",
                    frame=frame, meta={"track": tid})
