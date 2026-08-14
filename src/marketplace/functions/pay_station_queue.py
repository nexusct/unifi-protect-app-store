"""Pay Station Queue — line at the parking pay machine.

Persons queued at the pay-station zone past a count/dwell threshold.
Parking operators learn when machines jam or confuse users before the
1-star reviews land.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "pay-station-queue",
    "name": "Pay Station Queue",
    "tagline": "Four people deep at the pay machine at 5:55pm. One of them is about to bail on the ticket.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pay station approach",
        "max_queue": "int (default 3)",
        "hold_seconds": "int (default 45)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_q = int(self.settings.get("max_queue", 3))
        self.hold = float(self.settings.get("hold_seconds", 45))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pay_station")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_q:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Pay station queue: {count}",
                    detail=f"{count} people at pay station on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"queue": count})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
