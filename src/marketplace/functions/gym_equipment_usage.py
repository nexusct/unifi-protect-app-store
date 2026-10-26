"""Gym Equipment Usage — which machines get used, which gather dust.

Per-station zone dwell from member traffic: usage minutes per machine per
day. The data behind "do we buy another leg press or another rower" and
capex justification for gym operators.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "gym-equipment-usage",
    "name": "Equipment Usage Analytics",
    "tagline": "Estimates occupied time for configured equipment zones and emits a daily summary.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "stations": "map of machine-name → polygon",
        "digest_hour": "int (default 22)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 22))
        self._tracker = ZoneTracker()
        self._usage = defaultdict(float)
        self._last_ts = {}
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        stations = (camera.get("zones") or {}).get("stations") or {}
        if not stations:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            dt = max(0.0, ts - self._last_ts.get(tid, ts))
            self._last_ts[tid] = ts
            for name, poly in stations.items():
                _, _, st = self._tracker.update((camera["id"], name, tid), in_zone(cx, cy, poly), ts)
                if st["in"]:
                    self._usage[name] += dt
        tm = site_time(ts, ctx)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._usage:
            top = sorted(self._usage.items(), key=lambda x: x[1], reverse=True)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Daily equipment usage",
                detail=" | ".join(f"{n}: {v/60:.0f} min" for n, v in top[:8]),
                frame=None, meta={"usage_min": {n: round(v / 60, 1) for n, v in top}})
            self._usage.clear()
            self._last_day = day
