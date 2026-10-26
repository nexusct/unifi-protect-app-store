"""Service Response Time — elapsed time between configured zone signals.

Starts timing while a person-class detection is present in a trigger zone and
reports elapsed time when a person-class detection also appears in the arrival
zone. The signal does not determine identity, role, or service completion.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "service-response-time",
    "name": "Service Response Time",
    "tagline": "Measures elapsed time between person-class detections in configured trigger and arrival zones for operational review.",
    "category": "Intelligence",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "trigger_zone": "polygon — timing trigger area",
        "staff_zone": "polygon — timing arrival area",
        "target_seconds": "Response-time review threshold in seconds (default: 180).",
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
        elif not customer_waiting:
            self._triggered = None
        if self._triggered is not None and staff_arrived:
            response = ts - self._triggered
            self._triggered = None
            over = response > self.target
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Response {response:.0f}s {'(OVER TARGET)' if over else '(on target)'}",
                detail=f"Trigger-zone to arrival-zone detection interval {response:.0f}s vs {self.target:.0f}s review threshold on {camera['name']}.",
                frame=None, meta={"response_s": response, "target_s": self.target, "over": over})
