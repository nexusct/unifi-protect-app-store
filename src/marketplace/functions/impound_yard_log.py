"""Impound-yard vehicle line-crossing log.

Records observed vehicle-track crossings with direction and time for review.
The visual log does not establish billing facts or replace authoritative records.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line

MANIFEST = {
    "id": "impound-yard-log",
    "name": "Impound Yard In/Out Log",
    "tagline": "Records observed vehicle entry and exit times at configured impound-yard zones for billing review.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "line": "2-point yard crossing line",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._prev = {}
        self._counted = set()

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("yard_line")
        if not line or len(line) != 2:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            prev = self._prev.get(tid)
            self._prev[tid] = (cx, cy)
            if prev is None or tid in self._counted:
                continue
            d = crossed_line(prev, (cx, cy), line)
            if d != 0:
                self._counted.add(tid)
                direction = "IN" if d > 0 else "OUT"
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Vehicle {direction} — yard log",
                    detail=f"Vehicle crossed yard line {direction} on {camera['name']}.",
                    frame=frame, meta={"direction": direction, "track": tid})
