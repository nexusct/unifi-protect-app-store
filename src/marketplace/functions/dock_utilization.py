"""Dock Utilization — which dock doors are occupied, for how long.

Truck present per dock zone → per-door occupied time and daily utilization
percent. Ends the "we need more docks / no we don't" argument with data.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "dock-utilization",
    "name": "Dock Door Utilization",
    "tagline": "Summarizes observed busy and idle time for configured dock-door zones.",
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
        self.summary_hour = int(self.settings.get("summary_hour", 23))
        self._day = None
        self._reported_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        docks = (camera.get("zones") or {}).get("docks") or {}
        if not docks:
            return
        day = _t.strftime("%Y-%m-%d", site_time(ts, ctx))
        if self._day != day:
            self._state.clear()
            self._day_start = ts
            self._day = day
        boxes = boxes_of(frame, classes=list(TRUCKS))
        for name, poly in docks.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            st = self._state[(camera["id"], name)]
            if occupied and not st["occupied"]:
                st["occupied"] = True; st["since"] = ts
            elif not occupied and st["occupied"]:
                st["busy_total"] += ts - st["since"]
                st["occupied"] = False
                st["since"] = None
        if site_time(ts, ctx).tm_hour == self.summary_hour and self._reported_day != day:
            elapsed = max(1.0, ts - self._day_start)
            summary = {}
            for name in docks:
                st = self._state[(camera["id"], name)]
                busy = st["busy_total"]
                if st["occupied"] and st["since"] is not None:
                    busy += ts - st["since"]
                summary[name] = round(min(100.0, busy / elapsed * 100), 1)
            ctx.alerts.fire(
                site=ctx.site,
                camera=camera,
                detector=MANIFEST["id"],
                title="Dock utilization summary",
                detail=", ".join(f"{name}: {percent:.1f}% observed busy" for name, percent in sorted(summary.items())),
                frame=None,
                meta={"utilization_percent": summary, "elapsed_seconds": elapsed},
            )
            self._reported_day = day
