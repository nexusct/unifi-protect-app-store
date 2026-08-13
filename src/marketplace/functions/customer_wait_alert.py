"""Customer Wait Alert — unacknowledged customer detection.

A person standing in a service zone (counter, lobby desk, service bay)
with no staff nearby for longer than the threshold fires a service alert.
The metric behind "we didn't even greet them" reviews.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "customer-wait-alert",
    "name": "Unacknowledged Customer Alert",
    "tagline": "Nobody greeted them for 3 minutes. Now you know.",
    "category": "Retail & QSR",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — customer service area",
        "staff_zone": "polygon — where staff are expected",
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
                    title=f"Customer waiting {waited/60:.1f} min unacknowledged",
                    detail=f"Service zone on {camera['name']} occupied {waited:.0f}s with no staff present.",
                    frame=frame, meta={"wait_seconds": waited})
                self._waiting.pop(tid)
