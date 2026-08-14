"""Lot Inventory Count — overnight dealership vehicle count by row.

Counts vehicles per row zone during the quiet hours. The daily inventory
sanity check against the DMS — finds moved, missing, or mis-parked stock
before the lot manager does.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "lot-inventory-count",
    "name": "Lot Inventory Count",
    "tagline": "Row D is one car short vs the DMS. Found at 3am, not at month-end.",
    "category": "Automotive & Parking",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "rows": "map of row-name → polygon",
        "count_hour": "int — quiet-hours count (default 3)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.count_hour = int(self.settings.get("count_hour", 3))
        self._done_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        rows = (camera.get("zones") or {}).get("rows") or {}
        if not rows:
            return
        tm = _t.gmtime(ts)
        if tm.tm_hour != self.count_hour:
            return
        day = _t.strftime("%Y-%m-%d", tm)
        if self._done_day == day:
            return
        self._done_day = day
        boxes = boxes_of(frame, classes=list(VEHICLES))
        counts = {name: sum(1 for (_, cx, cy, *_r) in boxes if in_zone(cx, cy, poly))
                  for name, poly in rows.items()}
        ctx.alerts.fire(
            site=ctx.site, camera=camera, detector=MANIFEST["id"],
            title="Overnight lot count",
            detail=" | ".join(f"{n}: {c}" for n, c in sorted(counts.items())),
            frame=frame, meta={"counts": counts})
