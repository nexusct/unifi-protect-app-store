"""Clubhouse Flow — member traffic counts per amenity zone.

Counts member presence per zone (grill, pro shop, locker, patio) by hour.
Club managers staff to the real pattern, and the board gets amenity-usage
numbers for dues conversations.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "clubhouse-flow",
    "name": "Clubhouse Amenity Flow",
    "tagline": "The patio does 3x the grill on Fridays. Staffing finally matches.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zones": "map of amenity-name → polygon",
        "digest_hour": "int (default 22)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 22))
        self._visits = defaultdict(set)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zones = (camera.get("zones") or {}).get("amenities") or {}
        if not zones:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            for name, poly in zones.items():
                if in_zone(cx, cy, poly):
                    self._visits[name].add(tid)
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._visits:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Amenity visits today",
                detail=" | ".join(f"{n}: {len(s)} visitors" for n, s in sorted(self._visits.items())),
                frame=None, meta={"visitors": {n: len(s) for n, s in self._visits.items()}})
            self._visits.clear()
            self._last_day = day
