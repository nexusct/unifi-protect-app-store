"""Pace of Play — gap timing between groups at tee zones.

Measures the interval between cart groups at consecutive tee zones. A gap
over the threshold = slow group on the course. Marshals get the hole and
the gap, not a radio argument.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pace-of-play",
    "name": "Pace of Play Monitor",
    "tagline": "Flags unusually long gaps between tracked groups or carts on configured course zones for marshal review.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — tee box approach",
        "slow_gap_minutes": "int (default 15)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_gap_minutes", 15)) * 60
        self._last_group = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("tee")
        if not zone:
            return
        # a "group" = any person presence in the tee zone; record when zone clears after occupation
        occupied = any(in_zone(cx, cy, zone) for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]))
        key = camera["id"]
        if occupied:
            if key in self._last_group and ts - self._last_group[key] >= self.slow:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Slow gap: {(ts - self._last_group[key])/60:.0f} min",
                    detail=f"Tee zone empty {(ts - self._last_group[key])/60:.0f} minutes before this group on {camera['name']}.",
                    frame=frame, meta={"gap_min": (ts - self._last_group[key]) / 60})
                self._last_group.pop(key, None)
        else:
            self._last_group.setdefault(key, ts)
