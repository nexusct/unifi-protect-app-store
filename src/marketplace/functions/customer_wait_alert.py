"""Service-Zone Dwell Alert.

Reports a tracked person-class detection that remains in a configured service
zone while no person-class detection appears in a comparison zone. It does not
determine role, service status, or whether an interaction occurred.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "customer-wait-alert",
    "name": "Service-Zone Dwell Alert",
    "tagline": "Flags tracked person dwell in a service zone when a configured comparison zone has no person detection.",
    "category": "Retail & QSR",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — monitored service area",
        "staff_zone": "polygon — person-presence comparison area",
        "wait_seconds": "int — threshold (default 180)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.wait = float(self.settings.get("wait_seconds", 180))
        self._waiting = {}

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        cust_zone, staff_zone = zones.get("service"), zones.get("staff")
        if not cust_zone:
            return
        boxes = boxes_of(frame, classes=[0])
        customers = [t for (_, cx, cy, *_r, t) in boxes if in_zone(cx, cy, cust_zone) and t is not None]
        staff_present = any(in_zone(cx, cy, staff_zone) for (_, cx, cy, *_r) in boxes) if staff_zone else False
        for tid in customers:
            self._waiting.setdefault(tid, ts)
        for tid in list(self._waiting):
            if tid not in customers:
                self._waiting.pop(tid)
                continue
            waited = ts - self._waiting[tid]
            if waited >= self.wait and not staff_present:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Service-zone dwell {waited/60:.1f} min",
                    detail=f"Tracked person detection remained in the service zone on {camera['name']} for {waited:.0f}s with no person detection in the comparison zone.",
                    frame=frame, meta={"wait_seconds": waited})
                self._waiting.pop(tid)
