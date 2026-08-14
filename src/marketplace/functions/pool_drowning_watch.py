"""Pool Drowning Watch — person motionless in the water zone.

Person enters the water zone then stops moving beyond the threshold.
Distinct from pool capacity: this is the distress signature. Hotels, gyms,
multi-family, schools — the worst-case scenario function.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pool-drowning-watch",
    "name": "Pool Distress Watch",
    "tagline": "Motionless in the water for 20 seconds. This is the call that matters.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — water only (not deck)",
        "still_seconds": "int (default 20)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("still_seconds", 20))
        self._prev = {}
        self._still_since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("water")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0], conf=0.4):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None:
                continue
            moved = ((cx - prev[0]) ** 2 + (cy - prev[1]) ** 2) ** 0.5
            if moved < 0.004:
                self._still_since.setdefault(tid, ts)
                if ts - self._still_since[tid] >= self.limit:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="POSSIBLE POOL DISTRESS",
                        detail=f"Person motionless in water zone {ts - self._still_since[tid]:.0f}s on {camera['name']}.",
                        frame=frame, meta={"still_s": ts - self._still_since[tid]})
                    self._still_since[tid] = ts
            else:
                self._still_since.pop(tid, None)
