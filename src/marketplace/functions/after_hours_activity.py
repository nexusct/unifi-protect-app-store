"""After-Hours Activity — any person in the building outside open hours.

Simplest high-value function in the catalog: person detected during
closed hours = clip + immediate alert. The baseline every small business
wants from an alarm system without the alarm-system contract.
"""
from marketplace.contract import MarketplaceFunction, boxes_of

MANIFEST = {
    "id": "after-hours-activity",
    "name": "After-Hours Activity",
    "tagline": "Person in the building at 2am. Clip attached. Your phone, not your answering service.",
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
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
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
