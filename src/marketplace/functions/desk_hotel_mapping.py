"""Desk Hoteling Map — which desks get used in a flex office.

Per-desk zone occupancy across the day → utilization heat data for the
workplace team. Lease-renewal and floor-plan decisions with real numbers
instead of badge-swipe guesses.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "desk-hotel-mapping",
    "name": "Desk Utilization Map",
    "tagline": "Summarizes observed desk-zone occupancy patterns by location and time window.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "desks": "map of desk-name → polygon",
        "digest_hour": "int (default 17)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 17))
        self._occ = defaultdict(float)
        self._last = None
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        desks = (camera.get("zones") or {}).get("desks") or {}
        if not desks:
            return
        dt = ts - (self._last or ts)
        self._last = ts
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            for name, poly in desks.items():
                if in_zone(cx, cy, poly):
                    self._occ[name] += max(dt, 0)
                    break
        tm = site_time(ts, ctx)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._occ:
            total = sum(self._occ.values())
            used = sum(1 for v in self._occ.values() if v > 300)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Desk utilization: {used}/{len(desks)} used",
                detail=f"{used} of {len(desks)} desks used >5 min today on {camera['name']}.",
                frame=None, meta={"used": used, "total": len(desks)})
            self._occ.clear()
            self._last_day = day
