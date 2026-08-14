"""Driver Cab Time — person in the cab zone while trailer is at dock.

Driver-in-cab during loading is a dock-safety interlock (premature
departure risk). Person detected in the cab region while the dock zone
shows active work = safety alert to the dock supervisor.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "driver-cab-time",
    "name": "Driver-in-Cab Dock Interlock",
    "tagline": "Driver in the cab while the forklift's in the trailer. Alert the dock.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "cab_zone": "polygon — truck cab area",
        "dock_zone": "polygon — active dock",
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
                title="Driver in cab during active loading",
                detail=f"Person in cab zone while dock work active on {camera['name']} — premature-departure risk.",
                frame=frame, meta={})
