"""Supply Theft Watch — supply-zone presence outside work windows.

Feed, seed, chemical, and parts storage zones watched outside chore
windows. The function reports observed approaches for review and can attach a
JPEG snapshot; it does not determine theft or intent.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "supply-theft-watch",
    "name": "After-Hours Supply-Zone Activity",
    "tagline": "Flags person presence in the configured supply zone outside work hours and saves a local alert snapshot.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — supply storage",
        "work_hours": "[start,end] (default [6,19])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("work_hours", [6, 19])
        self._alerted = 0

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("supply")
        if not zone:
            return
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        s, e = int(self.hours[0]), int(self.hours[1])
        if (s <= hour < e) if s < e else (hour >= s or hour < e):
            return
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        if persons and ts - self._alerted > 300:
            self._alerted = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Supply zone presence off-hours",
                detail=f"{len(persons)} person(s) at supply storage on {camera['name']} outside work hours.",
                frame=frame, meta={"persons": len(persons)})
