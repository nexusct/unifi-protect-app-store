"""Service Response Time — alert-to-staff-arrival measurement.

Pair a trigger zone (service call button area, help point, queue spike)
with a staff-arrival zone: measures how long until a staff member reaches
the trigger after a customer event. The response-time KPI hospitals,
retailers, and hotels all claim but few measure.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "service-response-time",
    "name": "Service Response Time",
    "tagline": "Customer needed help at 2:04:12. Staff arrived 2:07:48. Measured, every time.",
    "category": "Intelligence",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "trigger_zone": "polygon — customer trigger point",
        "staff_zone": "polygon — where staff arrive",
        "target_seconds": "int — SLA target (default 180)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.target = float(self.settings.get("target_seconds", 180))
        self._triggered = None

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        trig, staff = zones.get("trigger"), zones.get("staff_arrive")
        if not trig or not staff:
            return
        boxes = boxes_of(frame, classes=[0])
        customer_waiting = any(in_zone(cx, cy, trig) for (_, cx, cy, *_r) in boxes)
        staff_arrived = any(in_zone(cx, cy, staff) for (_, cx, cy, *_r) in boxes)
        if customer_waiting and self._triggered is None:
            self._triggered = ts
        if self._triggered and staff_arrived:
            response = ts - self._triggered
            self._triggered = None
            over = response > self.target
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Response {response:.0f}s {'(OVER TARGET)' if over else '(on target)'}",
                detail=f"Customer-to-staff response {response:.0f}s vs {self.target:.0f}s target on {camera['name']}.",
                frame=None, meta={"response_s": response, "target_s": self.target, "over": over})
