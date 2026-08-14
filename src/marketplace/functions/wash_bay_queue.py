"""Wash Bay Queue — truck wash / service bay line length.

Counts vehicles waiting at the wash bay or service lane and times each
one. Fleet operators staff the wash on data instead of complaints.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "wash-bay-queue",
    "name": "Service Bay Queue",
    "tagline": "Five trucks deep at the wash bay at shift change. Dispatch already knows.",
    "category": "Manufacturing & Warehouse",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — queue lane",
        "max_queue": "int (default 3)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_q = int(self.settings.get("max_queue", 3))
        self._tracker = ZoneTracker()
        self._alerted_at = 0

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("bay_queue")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=list(VEHICLES)) if in_zone(cx, cy, zone))
        if count > self.max_q and ts - self._alerted_at > 300:
            self._alerted_at = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Bay queue at {count}",
                detail=f"{count} vehicles waiting at service bay on {camera['name']}.",
                frame=frame, meta={"queue": count})
