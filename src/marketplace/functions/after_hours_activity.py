"""After-Hours Activity — any person in the building outside open hours.

Person-class presence during configured closed hours produces an alert and,
unless privacy mode suppresses it, a JPEG review snapshot.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of

MANIFEST = {
    "id": "after-hours-activity",
    "name": "After-Hours Activity",
    "tagline": "Flags a detected person during configured closed hours and saves a local alert snapshot; routing depends on site configuration.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "closed_hours": "[start,end] (default [20,6])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("closed_hours", [20, 6])

    def process(self, camera, frame, ts, ctx):
        import time as _t
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        s, e = int(self.hours[0]), int(self.hours[1])
        closed = (hour >= s or hour < e) if s > e else (s <= hour < e)
        if not closed:
            return
        persons = boxes_of(frame, classes=[0], conf=0.5)
        if persons:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Person detected after hours",
                detail=f"{len(persons)} person(s) on {camera['name']} during closed hours.",
                frame=frame, meta={"persons": len(persons)})
