"""Drive-Thru Timer — per-vehicle service time from order point to exit.

Tracks vehicles from the order zone to the exit zone and logs the service
duration per car. Slow-car alerts past threshold; daily average in the
digest. The metric QSR franchises are scored on.
"""
import time as _t
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "drive-thru-timer",
    "name": "Drive-Thru Service Timer",
    "tagline": "Measures observed vehicle time between configured order-point and exit zones.",
    "category": "Retail & QSR",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "order_zone": "polygon — speaker/order point",
        "exit_zone": "polygon — past the window",
        "slow_seconds": "int — per-car alert threshold (default 240)",
    },
}

VEHICLES = (2, 3, 5, 7)  # car, motorcycle, bus, truck


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.slow = float(self.settings.get("slow_seconds", 240))
        self._tracker = ZoneTracker()
        self._entered = {}
        self._times = defaultdict(list)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        order, exit_ = zones.get("order"), zones.get("exit")
        if not order or not exit_:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            key = (camera["id"], tid)
            entered, _, _ = self._tracker.update(key, in_zone(cx, cy, order), ts)
            if entered:
                self._entered[tid] = ts
            if tid in self._entered and in_zone(cx, cy, exit_):
                dur = ts - self._entered.pop(tid)
                self._times[_t.strftime("%Y-%m-%d", site_time(ts, ctx))].append(dur)
                if dur >= self.slow:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Slow car: {dur/60:.1f} min",
                        detail=f"Vehicle spent {dur:.0f}s from order to exit on {camera['name']}.",
                        frame=frame, meta={"duration_s": dur})
