"""Forklift Speed Governor — speed estimation in pedestrian zones.

Pixel displacement per second across a calibrated pedestrian-shared zone.
Over the threshold = speed alert with the track. The cheapest forklift
safety program a warehouse can buy — no telematics retrofit required.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "forklift-speed",
    "name": "Forklift Speed Governor",
    "tagline": "Speeding forklifts in pedestrian aisles, caught on camera you already own.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pedestrian-shared lane",
        "max_px_per_sec": "float — calibrated speed proxy (default 0.15 normalized/s)",
    },
}

VEHICLES = (2, 3, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_speed = float(self.settings.get("max_px_per_sec", 0.15))
        self._prev = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("lane")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            prev = self._prev.get(tid)
            if prev:
                px, py, pts = prev
                dt = max(ts - pts, 1e-3)
                speed = (((cx - px) ** 2 + (cy - py) ** 2) ** 0.5) / dt
                if speed > self.max_speed:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="Forklift speeding in shared lane",
                        detail=f"Vehicle moving at {speed:.2f} norm/s (limit {self.max_speed}) on {camera['name']}.",
                        frame=frame, meta={"speed": round(speed, 3), "track": tid})
            self._prev[tid] = (cx, cy, ts)
