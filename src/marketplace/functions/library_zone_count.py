"""Library Zone Count — reading-room occupancy trends for libraries.

Per-zone visitor counts by hour across reading rooms, stacks, and kids'
areas. Libraries justify budgets with door counts and zone usage — this
produces both without patron-tracking privacy issues (counts only).
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "library-zone-count",
    "name": "Library Zone Counts",
    "tagline": "Summarizes estimated occupancy by configured library zone and time window.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zones": "map of zone-name → polygon",
        "digest_hour": "int (default 20)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 20))
        self._visits = defaultdict(set)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zones = (camera.get("zones") or {}).get("zones") or {}
        if not zones:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            for name, poly in zones.items():
                if in_zone(cx, cy, poly):
                    self._visits[name].add(tid)
        tm = site_time(ts, ctx)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._visits:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Zone visitors today",
                detail=" | ".join(f"{n}: {len(s)}" for n, s in sorted(self._visits.items())),
                frame=None, meta={"visitors": {n: len(s) for n, s in self._visits.items()}})
            self._visits.clear()
            self._last_day = day
