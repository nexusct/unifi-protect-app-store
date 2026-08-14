"""Service Lane Cycle — write-up to exit timing per vehicle (dealerships).

Vehicle enters the service write-up lane → exits the service exit zone.
Per-vehicle cycle time feeds the fixed-ops KPI dealerships report to the
OEM. Long-cycle alerts catch the bottleneck live.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "service-lane-cycle",
    "name": "Service Lane Cycle Time",
    "tagline": "Average write-up-to-exit: 3h 12m today. The OEM scorecard knows — now you do too.",
    "category": "Automotive & Parking",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "entry_zone": "polygon — write-up lane",
        "exit_zone": "polygon — service exit",
        "slow_hours": "float (default 5)",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_hours", 5)) * 3600
        self._entered = {}
        self._cycles = []

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        entry, exit_ = zones.get("service_entry"), zones.get("service_exit")
        if not entry or not exit_:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            if in_zone(cx, cy, entry):
                self._entered.setdefault(tid, ts)
            if in_zone(cx, cy, exit_):
                present.add(tid)
        for tid, entered in list(self._entered.items()):
            if tid in present:
                dur = ts - entered
                del self._entered[tid]
                self._cycles.append(dur)
                if dur >= self.slow:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Slow service cycle {dur/3600:.1f}h",
                        detail=f"Vehicle took {dur/3600:.1f}h entry-to-exit on {camera['name']}.",
                        frame=frame, meta={"hours": round(dur / 3600, 2)})
