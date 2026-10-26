"""Sanctuary Count — service attendance per service window.

Person-count peak in the sanctuary zone during each configured service
window. Churches track attendance for planning and reporting; this
automates the clicker.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "sanctuary-count",
    "name": "Service Attendance Count",
    "tagline": "Counts detected people in the configured sanctuary zone during service windows.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — sanctuary",
        "service_windows": "[[start,end],...] hours (default [[9,10],[11,12]])",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("service_windows", [[9, 10], [11, 12]])
        self._peak = {}
        self._reported = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("sanctuary")
        if not zone:
            return
        tm = site_time(ts, ctx)
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        for i, w in enumerate(self.windows):
            s, e = int(w[0]), int(w[1])
            key = f"{tm.tm_year}-{tm.tm_yday}-{i}"
            if s <= tm.tm_hour < e:
                self._peak[key] = max(self._peak.get(key, 0), count)
            elif tm.tm_hour >= e and key in self._peak and key not in self._reported:
                self._reported.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Service attendance: {self._peak[key]}",
                    detail=f"Peak {self._peak[key]} in the {s}:00 service window on {camera['name']}.",
                    frame=None, meta={"peak": self._peak[key], "window": [s, e]})
