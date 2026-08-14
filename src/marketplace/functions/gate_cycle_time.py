"""Gate Cycle Time — inbound gate open-to-clear duration per truck.

Tracks gate-zone occupation time per vehicle: the gate throughput KPI
for distribution centers. Slow gates back up the street; this measures it.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "gate-cycle-time",
    "name": "Gate Cycle Time",
    "tagline": "2:40 average at the inbound gate. Peak hours hit 7 minutes. Now it's measured.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — gate lane",
        "slow_seconds": "int (default 300)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_seconds", 300))
        self._tracker = ZoneTracker()
        self._cycles = []

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("gate")
        if not zone:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            present.add(tid)
            self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
        for key, st in list(self._tracker.state.items()):
            tid = key[1]
            if st["in"] and tid not in present and st["since"]:
                dur = ts - st["since"]
                self._cycles.append(dur)
                st["in"] = False
                st["since"] = None
                if dur >= self.slow:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Slow gate cycle {dur/60:.1f} min",
                        detail=f"Vehicle occupied gate {dur:.0f}s on {camera['name']}.",
                        frame=frame, meta={"cycle_s": dur})
