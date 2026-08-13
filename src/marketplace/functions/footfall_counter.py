"""Footfall Counter — directional in/out counting + live occupancy.

A counting line at the entrance; tracks direction per person ID. Emits
hourly counts and current occupancy — the baseline metric every retail,
library, gym, and venue operator wants but few can afford from vendors.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "footfall-counter",
    "name": "Footfall & Occupancy Counter",
    "tagline": "Real door counts and live occupancy, from the camera you already own.",
    "category": "Retail & QSR",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "count_line": "2-point line across the entrance",
        "occupancy_alert": "int — optional max occupancy alert",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_occ = self.settings.get("occupancy_alert")
        self._prev = {}
        self._counted = set()
        self.ins = 0
        self.outs = 0

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("count_line")
        if not line or len(line) != 2:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None or tid in self._counted:
                continue
            d = crossed_line(prev, (cx, cy), line)
            if d > 0:
                self.ins += 1; self._counted.add(tid)
            elif d < 0:
                self.outs += 1; self._counted.add(tid)
        occ = self.ins - self.outs
        if self.max_occ and occ >= int(self.max_occ):
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Occupancy at {occ}",
                detail=f"Live occupancy {occ} reached configured limit on {camera['name']}.",
                frame=frame, meta={"in": self.ins, "out": self.outs, "occupancy": occ})
