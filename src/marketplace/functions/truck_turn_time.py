"""Tracked-truck dwell estimate for a configured yard or dock zone."""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "truck-turn-time",
    "name": "Truck Yard Dwell Estimate",
    "tagline": "Measures tracked-truck dwell from first presence in a configured yard or dock zone until the track leaves; it does not identify carriers.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "Polygon for the yard or dock area to monitor.",
        "slow_minutes": "Minutes of continuous tracked presence before review (default 120).",
    },
}

TRUCKS = (5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_minutes", 120)) * 60
        self._inside = {}
        self._turns = []

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("yard")
        if not zone:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(TRUCKS)):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            present.add(tid)
            self._inside.setdefault(tid, ts)
        for tid, entered in list(self._inside.items()):
            if tid not in present:
                dur = ts - entered
                del self._inside[tid]
                self._turns.append(dur)
                if dur >= self.slow:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Truck-track dwell {dur/60:.0f} min",
                        detail=f"Truck track remained in the configured yard zone for {dur/60:.1f} min on {camera['name']}.",
                        frame=frame, meta={"turn_minutes": round(dur / 60, 1)})
