"""Wash/Detail Bay Pace — per-bay turn time for car washes.

Vehicle enters bay zone → leaves bay zone = turn time. Express washes live
on cars-per-hour per bay; this measures it and flags stalled bays.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "wash-bay-pace",
    "name": "Wash Bay Dwell Review",
    "tagline": "Flags a vehicle remaining in a configured bay beyond the set duration; it does not compare bays by percentage.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "bays": "map of bay-name → polygon",
        "slow_seconds": "int (default 420)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_seconds", 420))
        self._state = defaultdict(lambda: {"in": False, "since": None})
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        bays = (camera.get("zones") or {}).get("bays") or {}
        if not bays:
            return
        boxes = boxes_of(frame, classes=list(VEHICLES))
        for name, poly in bays.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            key = (camera["id"], name)
            st = self._state[key]
            if occupied and not st["in"]:
                st["in"] = True; st["since"] = ts
            elif occupied and st["since"] and ts - st["since"] >= self.slow and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"{name} running slow",
                    detail=f"Vehicle in {name} for {(ts - st['since'])/60:.1f} min on {camera['name']}.",
                    frame=frame, meta={"bay": name, "minutes": (ts - st["since"]) / 60})
            elif not occupied and st["in"]:
                st["in"] = False; st["since"] = None
                self._alerted.discard(key)
