"""Pump Dwell — vehicle camping at the pump past the fueling window.

Tracks per-pump occupation time. Slow pumps kill forecourt throughput at
rush hour; the metric also feeds the "pump turns per day" KPI c-stores
report on.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "pump-dwell",
    "name": "Pump Dwell Time",
    "tagline": "A car camping at pump 4 during rush costs you three sales an hour.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pump island",
        "slow_minutes": "int (default 12)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_minutes", 12)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pump")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, _, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"] and st["since"] and ts - st["since"] >= self.slow and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Pump occupied {(ts - st['since'])/60:.0f} min",
                    detail=f"Vehicle at pump past {self.slow/60:.0f}-min window on {camera['name']}.",
                    frame=frame, meta={"dwell_min": (ts - st["since"]) / 60})
            if not st["in"]:
                self._alerted.discard(key)
