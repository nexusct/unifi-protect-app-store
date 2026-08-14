"""Overnight Parking — vehicle in a posted lot past closing.

Municipal lots, retail lots, trailhead lots: vehicle present during
posted no-overnight hours = log + alert. Parking enforcement and property
management both bill this as a service.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "overnight-parking",
    "name": "Overnight Parking Watch",
    "tagline": "Posted no overnight parking. There's a van. It's 2am. Documented.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — lot area",
        "closed_hours": "[start,end] (default [22,6])",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("closed_hours", [22, 6])
        self._reported = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("lot")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        s, e = int(self.hours[0]), int(self.hours[1])
        closed = (hour >= s or hour < e) if s > e else (s <= hour < e)
        if not closed:
            self._reported.clear()
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None or not in_zone(cx, cy, zone) or tid in self._reported:
                continue
            self._reported.add(tid)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Vehicle parked overnight",
                detail=f"Vehicle in posted lot during closed hours on {camera['name']}.",
                frame=frame, meta={"track": tid})
