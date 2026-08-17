"""Shared-Lane Vehicle Motion Alert — normalized image-space motion review.

Compares normalized tracked-object displacement with a camera-specific review
threshold. It does not measure physical speed without a separate calibration.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "forklift-speed",
    "name": "Shared-Lane Vehicle Motion Alert",
    "tagline": "Flags tracked vehicle motion above a camera-calibrated image-space threshold in a configured shared lane; human review required.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pedestrian-shared lane",
        "max_px_per_sec": "Number — calibrated normalized image-space motion threshold per second.",
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
                        title="Shared-lane vehicle motion above review threshold",
                        detail=f"Normalized image-space motion was {speed:.2f}/s versus the configured threshold {self.max_speed} on {camera['name']}; review the event rather than treating this as a physical speed measurement.",
                        frame=frame, meta={"speed": round(speed, 3), "track": tid})
            self._prev[tid] = (cx, cy, ts)
