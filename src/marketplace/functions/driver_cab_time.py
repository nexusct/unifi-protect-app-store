"""Cab/Dock Concurrent Presence — person detections in two configured zones.

Reports when person-class detections appear in both the cab and dock zones.
It does not determine role, work state, vehicle state, or operational risk.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "driver-cab-time",
    "name": "Cab/Dock Concurrent Presence",
    "tagline": "Flags simultaneous person-class detections in configured cab and dock zones for supervisor review.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "cab_zone": "polygon — truck cab area",
        "dock_zone": "polygon — monitored dock area",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        cab, dock = zones.get("cab"), zones.get("dock")
        if not cab or not dock:
            return
        boxes = boxes_of(frame, classes=[0])
        driver_in_cab = any(in_zone(cx, cy, cab) for (_, cx, cy, *_r) in boxes)
        dock_active = any(in_zone(cx, cy, dock) for (_, cx, cy, *_r) in boxes)
        key = camera["id"]
        if driver_in_cab and dock_active and ts - self._alerted.get(key, 0) > 180:
            self._alerted[key] = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Concurrent cab-zone and dock-zone presence",
                detail=f"Person-class detections appeared in both configured zones on {camera['name']}; review the image and operational context.",
                frame=frame, meta={})
