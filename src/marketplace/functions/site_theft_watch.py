"""Site Theft Watch — equipment-zone presence after crew hours.

Construction sites lose tools, copper, and fuel to after-hours visitors.
Person or vehicle in the laydown yard/equipment zone outside crew hours =
clip + alert. Builders get this for the insurance discount alone.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "site-theft-watch",
    "name": "Construction Site Theft Watch",
    "tagline": "Copper walks off at midnight. Now it walks off on camera, flagged.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — laydown yard / equipment",
        "crew_hours": "[start,end] (default [6,17])",
        "weekends_active": "bool (default true)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("crew_hours", [6, 17])
        self.weekends = self.settings.get("weekends_active", True)
        self._alerted = 0

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("yard")
        if not zone:
            return
        tm = _t.gmtime(ts)
        s, e = int(self.hours[0]), int(self.hours[1])
        crew = (s <= tm.tm_hour < e) and (tm.tm_wday < 5 or self.weekends is False)
        if crew:
            return
        hits = [b for b in boxes_of(frame, classes=[0, 2, 5, 7]) if in_zone(b[1], b[2], zone)]
        if hits and ts - self._alerted > 600:
            self._alerted = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Equipment zone presence off-hours",
                detail=f"{len(hits)} person/vehicle detection(s) in equipment zone on {camera['name']}.",
                frame=frame, meta={"detections": len(hits)})
