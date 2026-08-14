"""Bus Loop Safety — vehicle in the student loading zone during bells.

The bus loop is for buses at bell times. Any non-bus vehicle (or a person
in the drive lane) during the configured windows fires an immediate alert
to the front office.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "bus-loop-safety",
    "name": "Bus Loop Safety",
    "tagline": "A car in the bus loop at 8:15am is a headline you don't want.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — bus loop",
        "bell_windows": "[[start,end],...] hours (default [[7,9],[14,16]])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("bell_windows", [[7, 9], [14, 16]])
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("bus_loop")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        if not any(int(w[0]) <= hour < int(w[1]) for w in self.windows):
            self._alerted.clear()
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0, 2, 7]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            # buses (class 5) are fine; cars/persons/trucks in the loop during bells are not
            if cls == "bus":
                continue
            if ts - self._alerted.get(tid, 0) > 120:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"{cls.title()} in bus loop during bell window",
                    detail=f"{cls} detected in student loading zone on {camera['name']}.",
                    frame=frame, meta={"class": cls})
