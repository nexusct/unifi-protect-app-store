"""After-hours hallway person-presence signal.

Flags person detections in the configured corridor during selected hours. It
does not determine identity, authorization, tenancy, or intent.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "hallway-overnight",
    "name": "Hallway Overnight Presence",
    "tagline": "Flags person detections in configured building areas during selected after-hours for staff review.",
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
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
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
