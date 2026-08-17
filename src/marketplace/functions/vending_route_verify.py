"""Vending Route Verify — service-visit duration at machine banks.

Vending route accountability: did the driver actually service each bank
and for how long? Person dwell at each machine-bank zone, logged per
visit. The route report writes itself.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "vending-route-verify",
    "name": "Vending Route Verification",
    "tagline": "Logs possible service visits when person dwell at a configured vending-bank zone exceeds the selected threshold.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "banks": "map of bank-name → polygon",
        "min_service_seconds": "Minimum observed dwell used to classify a possible service visit (default: 180 seconds).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.min_service = float(self.settings.get("min_service_seconds", 180))
        self._tracker = ZoneTracker()
        self._reported = set()

    def process(self, camera, frame, ts, ctx):
        banks = (camera.get("zones") or {}).get("banks") or {}
        if not banks:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            for name, poly in banks.items():
                key = (camera["id"], name, tid)
                _, _, st = self._tracker.update(key, in_zone(cx, cy, poly), ts)
                if not st["in"] and st.get("last_dwell") is not None:
                    pass
                # on exit: report dwell
                if key in self._tracker.state:
                    s2 = self._tracker.state[key]
                    if not s2["in"] and key not in self._reported and s2["visits"]:
                        dwell = ts - s2["visits"][-1] if s2["visits"] else 0
                        if dwell > 5:
                            self._reported.add(key)
                            short = dwell < self.min_service
                            ctx.alerts.fire(
                                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                                title=f"{name}: {dwell/60:.1f}-min visit{' (SHORT)' if short else ''}",
                                detail=f"Service dwell {dwell:.0f}s at {name} on {camera['name']}.",
                                frame=None, meta={"bank": name, "dwell_s": dwell, "short": short})
