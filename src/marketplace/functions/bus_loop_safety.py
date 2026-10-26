"""Bus Loop Safety — vehicle in the student loading zone during bells.

The bus loop is for buses at bell times. Any non-bus vehicle (or a person
in the drive lane) during the configured windows fires an immediate alert
to the front office.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "bus-loop-safety",
    "name": "Bus Loop Safety",
    "tagline": "Flags vehicles detected in a configured bus-loop exclusion zone during selected school-arrival windows.",
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
        hour = int(_t.strftime("%H", site_time(ts, ctx)))
        if not any(int(w[0]) <= hour < int(w[1]) for w in self.windows):
            self._alerted.clear()
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0, 2, 5, 7]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            # buses (class 5) are fine; cars/persons/trucks in the loop during bells are not
            if cls == 5:
                continue
            if ts - self._alerted.get(tid, 0) > 120:
                self._alerted[tid] = ts
                label = {0: "person", 2: "car", 7: "truck"}.get(cls, f"class {cls}")
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"{label.title()} in bus loop during bell window",
                    detail=f"{label} detection in the configured loading zone on {camera['name']}.",
                    frame=frame, meta={"class_id": cls, "class_label": label})
