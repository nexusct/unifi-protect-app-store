"""After-hours person or vehicle presence in an equipment zone."""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "site-theft-watch",
    "name": "After-Hours Equipment-Zone Presence",
    "tagline": "Flags detected people or vehicles in a configured equipment zone outside scheduled crew hours; it does not establish theft.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "Polygon for the laydown yard or equipment area.",
        "crew_hours": "UTC start and end hours for scheduled crew presence (default [6, 17]).",
        "weekends_active": "Whether weekday crew hours also apply on weekends (default true).",
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
        tm = site_time(ts, ctx)
        s, e = int(self.hours[0]), int(self.hours[1])
        crew = (s <= tm.tm_hour < e) and (tm.tm_wday < 5 or self.weekends is True)
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
