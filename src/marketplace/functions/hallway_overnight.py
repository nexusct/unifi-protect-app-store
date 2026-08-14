"""Hallway Overnight — person in a storage hallway after office hours.

Interior corridor presence after close. Finds both the break-in and the
tenant quietly living in their unit (a real, documented self-storage
problem with legal exposure).
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "hallway-overnight",
    "name": "Hallway Overnight Presence",
    "tagline": "Someone is in building C at 2am. Tenant, thief, or resident — you need to know which.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — interior hallway",
        "after_hours": "[start,end] (default [21,6])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("after_hours", [21, 6])
        self._alerted = 0

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("hallway")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        s, e = int(self.hours[0]), int(self.hours[1])
        if not ((hour >= s or hour < e) if s > e else (s <= hour < e)):
            return
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        if persons and ts - self._alerted > 600:
            self._alerted = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Overnight hallway presence",
                detail=f"{len(persons)} person(s) in hallway on {camera['name']} after hours.",
                frame=frame, meta={"persons": len(persons)})
