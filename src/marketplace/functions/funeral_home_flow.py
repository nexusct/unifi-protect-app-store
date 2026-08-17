"""Visitation Flow — tracked zone entries during configured windows.

Counts distinct tracker IDs observed in a configured room zone. Tracker IDs
are camera-session artifacts and must not be interpreted as unique people.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "funeral-home-flow",
    "name": "Visitation Room Flow",
    "tagline": "Counts tracked entries into a configured visitation-room zone during scheduled windows.",
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
        tm = site_time(ts, ctx)
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
                    title=f"Visitation window: {len(self._visitors[key])} distinct track IDs",
                    detail=f"Observed {len(self._visitors[key])} distinct tracker IDs in the room zone during the {s}:00 window on {camera['name']}; this is not a unique-person count.",
                    frame=None, meta={"track_ids": len(self._visitors[key]), "window": [s, e]})
