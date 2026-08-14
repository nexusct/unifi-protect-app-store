"""Visitation Flow — visitation-room occupancy during scheduled visitations.

Occupancy minutes per visitation window, logged per room. Funeral homes
document service delivery for families and plan staff for large services.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "funeral-home-flow",
    "name": "Visitation Room Flow",
    "tagline": "The Johnson visitation ran 3 hours with 140 visitors. Documented for the family.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — visitation room",
        "visitation_windows": "[[start,end],...] hours",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("visitation_windows", [])
        self._visitors = defaultdict(set)
        self._reported = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("visitation")
        if not zone:
            return
        tm = _t.gmtime(ts)
        for i, w in enumerate(self.windows):
            s, e = int(w[0]), int(w[1])
            key = f"{tm.tm_year}-{tm.tm_yday}-{i}"
            if s <= tm.tm_hour < e:
                for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
                    if tid is not None and in_zone(cx, cy, zone):
                        self._visitors[key].add(tid)
            elif tm.tm_hour >= e and key in self._visitors and key not in self._reported:
                self._reported.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Visitation: {len(self._visitors[key])} visitors",
                    detail=f"{len(self._visitors[key])} unique visitors during the {s}:00 window on {camera['name']}.",
                    frame=None, meta={"visitors": len(self._visitors[key]), "window": [s, e]})
