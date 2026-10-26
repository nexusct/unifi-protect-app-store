"""Accessible Stall Monitor — usage log + rapid-turnover flag.

Logs visually estimated accessible-stall occupancy and flags rapid turnover
for property-manager review. It does not infer disability status or compliance.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "handicap-stall-monitor",
    "name": "Accessible Stall Usage Log",
    "tagline": "Logs observed accessible-stall occupancy and flags unusually short visits for property-manager review.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "stalls": "map of stall-name → polygon",
        "fast_minutes": "int — flag turns under this (default 3)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.fast = float(self.settings.get("fast_minutes", 3)) * 60
        self._state = defaultdict(lambda: {"in": False, "since": None})

    def process(self, camera, frame, ts, ctx):
        stalls = (camera.get("zones") or {}).get("accessible") or {}
        if not stalls:
            return
        boxes = boxes_of(frame, classes=list(VEHICLES))
        for name, poly in stalls.items():
            occupied = any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes)
            key = (camera["id"], name)
            st = self._state[key]
            if occupied and not st["in"]:
                st["in"] = True; st["since"] = ts
            elif not occupied and st["in"]:
                dur = ts - st["since"]
                st["in"] = False
                flag = " — FAST TURNOVER" if dur < self.fast else ""
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Accessible stall {name}: {dur/60:.1f} min{flag}",
                    detail=f"Stall {name} used {dur/60:.1f} minutes on {camera['name']}.{flag}",
                    frame=None, meta={"stall": name, "minutes": round(dur / 60, 1), "fast": dur < self.fast})
