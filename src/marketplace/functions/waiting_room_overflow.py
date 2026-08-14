"""Waiting Room Overflow — lobby census vs capacity with staff escalation.

Counts persons in the waiting area; past the threshold, front-desk gets a
"triage now" alert. Clinics live and die by perceived wait — this catches
the overflow before the bad review does.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "waiting-room-overflow",
    "name": "Waiting Room Overflow",
    "tagline": "The lobby hit 14 people at 9:12am. Triage got pinged at 9:12am.",
    "category": "Healthcare & Senior Living",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — waiting area",
        "max_persons": "int (default 12)",
        "hold_seconds": "int (default 60)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_n = int(self.settings.get("max_persons", 12))
        self.hold = float(self.settings.get("hold_seconds", 60))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("waiting")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_n:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Waiting room at {count}",
                    detail=f"{count} people waiting on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"count": count})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
