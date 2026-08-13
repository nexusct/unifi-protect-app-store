"""Curbside Arrival — pickup-customer arrival ping.

Vehicle enters the curbside zone → staff alert with lane + camera tag.
Pairs with ALPR for named-order matching when plate weights are present.
The curbside experience metric that QSR/retail competes on.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "curbside-arrival",
    "name": "Curbside Pickup Arrival",
    "tagline": "Customer in the pickup lane — staff know before the app notification.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — curbside lane",
    },
}

VEHICLES = (2, 3, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._tracker = ZoneTracker()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("curbside")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            entered, _, _ = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if entered:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Curbside arrival",
                    detail=f"Vehicle arrived in pickup lane on {camera['name']}.",
                    frame=frame, meta={"track": tid})
