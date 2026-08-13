"""Pallet Count — zone inventory from box-counting heuristics.

Counts pallet-sized objects in a staging zone per frame and tracks the
daily max/last counts — a video-derived inventory sanity check that
catches "the system says 40, the floor says 12" without a barcode scan.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pallet-count",
    "name": "Pallet Count",
    "tagline": "The floor count vs the system count — settled by camera.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — staging area",
        "min_area_ratio": "float — min object size vs frame (default 0.005)",
        "max_area_ratio": "float — max object size (default 0.15)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.min_a = float(self.settings.get("min_area_ratio", 0.005))
        self.max_a = float(self.settings.get("max_area_ratio", 0.15))
        self._peak = defaultdict(int)

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("staging")
        if not zone:
            return
        count = 0
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame):
            area = ((x2 - x1) * (y2 - y1)) / (frame.shape[0] * frame.shape[1])
            if in_zone(cx, cy, zone) and self.min_a <= area <= self.max_a and cls not in ("person",):
                count += 1
        day_key = camera["id"]
        if count > self._peak[day_key]:
            self._peak[day_key] = count
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Staging count: {count} pallets",
                detail=f"New peak count {count} in staging zone on {camera['name']}.",
                frame=frame, meta={"count": count})
