"""Gym Occupancy (class sizing) — group-fitness class headcount.

Counts persons in the studio zone per configured class windows and logs
actual attendance vs booked. Studios optimize schedules on real numbers,
not sign-up lies.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "gym-occupancy-class",
    "name": "Class Attendance Counter",
    "tagline": "12 booked, 5 showed. Now your schedule knows.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — studio floor",
        "class_windows": "[[start,end],...] hours",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("class_windows", [])
        self._peak = defaultdict(int)
        self._reported = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("studio")
        if not zone:
            return
        tm = _t.gmtime(ts)
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        for i, w in enumerate(self.windows):
            s, e = int(w[0]), int(w[1])
            if s <= tm.tm_hour < e:
                key = f"{tm.tm_year}-{tm.tm_yday}-{i}"
                self._peak[key] = max(self._peak[key], count)
                if tm.tm_hour == e - 1 and key not in self._reported:
                    self._reported.add(key)
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Class attendance: {self._peak[key]} peak",
                        detail=f"Peak {self._peak[key]} in studio class window {s}:00-{e}:00 on {camera['name']}.",
                        frame=None, meta={"peak": self._peak[key], "window": [s, e]})
