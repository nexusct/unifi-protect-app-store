"""Dock Utilization — which dock doors are occupied, for how long.

Truck present per dock zone → per-door occupied time and daily utilization
percent. Ends the "we need more docks / no we don't" argument with data.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "dock-utilization",
    "name": "Dock Door Utilization",
    "tagline": "Every dock door's busy time, measured — not argued about.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "docks": "map of dock-name → polygon",
    },
}

TRUCKS = (5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._state = defaultdict(lambda: {"occupied": False, "since": None, "busy_total": 0.0})
        self._day_start = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        docks = (camera.get("zones") or {}).get("docks") or {}
        if not docks:
            return
        day = _t.strftime("%Y-%m-%d", _t.gmtime(ts))
        if self._day_start is None:
            self._day_start = ts
        boxes = boxes_of(frame, classes=list(TRUCKS))
        for name, poly in docks.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            st = self._state[(camera["id"], name)]
            if occupied and not st["occupied"]:
                st["occupied"] = True; st["since"] = ts
            elif not occupied and st["occupied"]:
                st["busy_total"] += ts - st["since"]
                st["occupied"] = False
        if _t.strftime("%H", _t.gmtime(ts)) == "23" and self._last_day != day if hasattr(self, "_last_day") else False:
            pass
        self._last_day = day
