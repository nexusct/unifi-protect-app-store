"""Drive-Off Alert — vehicle departs the pump with no store-visit signature.

Heuristic: vehicle occupied a pump zone, no person track crossed the
store-entry line during the occupation, vehicle leaves. Fires while the
plate is still on camera (pairs with ALPR for the report).
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, crossed_line, in_zone

MANIFEST = {
    "id": "drive-off-alert",
    "name": "Drive-Off Alert",
    "tagline": "Flags a vehicle leaving a configured pump zone when no person crossing of the store-entry line was observed in the associated time bucket; review before action.",
    "category": "Automotive & Parking",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pump island",
        "store_line": "2-point line across store entry",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._tracker = ZoneTracker()
        self._sessions = {}
        self._paid = set()
        self._prev = {}

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        pump, line = zones.get("pump"), zones.get("store_line")
        if not pump or not line:
            return
        # watch for store-entry crossings (a "payment signature")
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev and crossed_line(prev, (cx, cy), line) != 0:
                self._paid.add(ts // 300)  # payment seen in this 5-min bucket
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            key = (camera["id"], tid)
            entered, _, st = self._tracker.update(key, in_zone(cx, cy, pump), ts)
            if entered:
                self._sessions[tid] = ts
            if not st["in"] and tid in self._sessions:
                occupied_at = self._sessions.pop(tid) // 300
                if occupied_at not in self._paid:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="Possible drive-off",
                        detail=f"Vehicle left pump with no store-entry during its visit on {camera['name']}.",
                        frame=frame, meta={"track": tid})
