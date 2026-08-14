"""Scrap Scale Queue — trucks queued at the scale house.

Queue length and cycle time at the inbound scale. Scrap yards and
recycling centers run on truck turns; this measures both and catches the
backing-up-onto-the-road problem early.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "scrap-scale-queue",
    "name": "Scale House Queue",
    "tagline": "Six trucks at the scale and one working it. Dispatch knows before the drivers call.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — scale approach lane",
        "max_queue": "int (default 4)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_q = int(self.settings.get("max_queue", 4))
        self._alerted = 0

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("scale_lane")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=list(VEHICLES)) if in_zone(cx, cy, zone))
        if count > self.max_q and ts - self._alerted > 900:
            self._alerted = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Scale queue: {count} trucks",
                detail=f"{count} trucks queued at the scale on {camera['name']}.",
                frame=frame, meta={"queue": count})
