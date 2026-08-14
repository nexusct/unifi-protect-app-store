"""Laundromat Overnight — person in the store during closed/unsafe hours.

24-hour laundromats have a vagrancy/safety problem; closed ones have a
break-in problem. Person presence during the configured window with clip.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "laundromat-overnight",
    "name": "Laundromat Overnight Watch",
    "tagline": "Someone's been sitting on the folding table for two hours at 3am.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — store floor",
        "watch_hours": "[start,end] (default [1,5])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("watch_hours", [1, 5])
        self._alerted = 0

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("floor")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        s, e = int(self.hours[0]), int(self.hours[1])
        if not ((hour >= s or hour < e) if s > e else (s <= hour < e)):
            return
        persons = [b for b in boxes_of(frame, classes=[0]) if in_zone(b[1], b[2], zone)]
        if persons and ts - self._alerted > 1800:
            self._alerted = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Overnight store presence",
                detail=f"{len(persons)} person(s) in laundromat during watch hours on {camera['name']}.",
                frame=frame, meta={"persons": len(persons)})
