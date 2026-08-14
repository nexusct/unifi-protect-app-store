"""Range Utilization — hitting-bay occupancy across the day.

Per-bay occupancy minutes for the driving range. Operators learn real
peak windows and dead bays — feeding pricing, staffing, and the "should
we extend the range" question.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "range-utilization",
    "name": "Driving Range Utilization",
    "tagline": "Bay 1-8 full until 10, dead by 2. The pricing sheet should know.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "bays": "map of bay-name → polygon",
        "digest_hour": "int (default 21)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 21))
        self._occ = defaultdict(float)
        self._last = None
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        bays = (camera.get("zones") or {}).get("bays") or {}
        if not bays:
            return
        dt = ts - (self._last or ts)
        self._last = ts
        boxes = boxes_of(frame, classes=[0])
        for name, poly in bays.items():
            if any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes):
                self._occ[name] += max(dt, 0)
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._occ:
            lines = sorted(self._occ.items(), key=lambda x: x[1], reverse=True)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Range utilization today",
                detail=" | ".join(f"{n}: {v/60:.0f} min" for n, v in lines[:10]),
                frame=None, meta={"minutes": {n: round(v / 60, 1) for n, v in lines}})
            self._occ.clear()
            self._last_day = day
