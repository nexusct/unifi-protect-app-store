"""Conveyor stalled-object review.

Flags a tracked non-person detection that remains nearly stationary in the
configured belt zone. Operators verify whether a jam or blockage exists.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "conveyor-jam",
    "name": "Conveyor Stalled-Object Review",
    "tagline": "Flags a tracked non-person object that remains nearly stationary in the belt zone beyond the configured threshold; operators verify a jam.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — belt area",
        "jam_seconds": "int — stationary threshold (default 20)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.jam_s = float(self.settings.get("jam_seconds", 20))
        self._prev = {}
        self._still_since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("belt")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame):
            if tid is None or not in_zone(cx, cy, zone) or cls == 0:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy, ts)
            if not prev:
                continue
            moved = ((cx - prev[0]) ** 2 + (cy - prev[1]) ** 2) ** 0.5
            if moved < 0.005:
                self._still_since.setdefault(tid, prev[2])
                if ts - self._still_since[tid] >= self.jam_s:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="Conveyor jam suspected",
                        detail=f"Object stationary {ts - self._still_since[tid]:.0f}s on belt zone, {camera['name']}.",
                        frame=frame, meta={"track": tid})
                    self._still_since.pop(tid, None)
            else:
                self._still_since.pop(tid, None)
