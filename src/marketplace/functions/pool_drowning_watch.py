"""Pool Low-Movement Review — limited tracked movement in a water zone.

Reports when a person-class track shows limited frame-to-frame image-space
movement for the configured duration. This proxy cannot diagnose distress and
does not replace lifeguards, supervision, or emergency procedures.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pool-drowning-watch",
    "name": "Pool Stillness Review",
    "tagline": "Flags a tracked person with limited image-space movement in the water zone; requires calibration, lifeguard review, and established emergency procedures.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — water only (not deck)",
        "still_seconds": "Low-movement review threshold in seconds (default: 20); calibrate and test for each view.",
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
                        title="Low tracked movement in pool zone",
                        detail=f"Person-class track showed limited image-space movement in the water zone for {ts - self._still_since[tid]:.0f}s on {camera['name']}; review immediately under site procedures.",
                        frame=frame, meta={"still_s": ts - self._still_since[tid]})
                    self._still_since[tid] = ts
            else:
                self._still_since.pop(tid, None)
