"""Hall Pass Monitor — students in corridors during class time.

Person detected in hallway zones during scheduled class blocks (with
passing-period gaps configured) = hall-roaming alert for deans. Schools
get corridor coverage without adding duty assignments.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "hall-pass-monitor",
    "name": "Hall Pass Monitor",
    "tagline": "Corridor roaming during class blocks, logged for the dean's office.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — hallway",
        "class_hours": "[start,end] (default [8,15])",
        "passing_minutes": "int — gap at hour start (default 10)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("class_hours", [8, 15])
        self.passing = int(self.settings.get("passing_minutes", 10))
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("hallway")
        if not zone:
            return
        tm = _t.gmtime(ts)
        if not (int(self.hours[0]) <= tm.tm_hour < int(self.hours[1])) or tm.tm_wday >= 5:
            return
        if tm.tm_min < self.passing:  # passing period at hour start
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            if ts - self._alerted.get(tid, 0) > 600:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Hallway presence during class",
                    detail=f"Person in corridor on {camera['name']} during a class block.",
                    frame=frame, meta={"track": tid})
