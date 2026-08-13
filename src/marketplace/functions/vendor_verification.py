"""Vendor Verification — is that really the vendor who was scheduled?

Correlates door-zone vehicle/person arrival times against a schedule
window (from settings or Base44 work orders via webhook). Arrival outside
the window = unscheduled-visit alert. The front desk's vendor log, automated.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "vendor-verification",
    "name": "Vendor Arrival Verification",
    "tagline": "Scheduled 9-11am. Arrived 6:40am. Flagged.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — vendor entrance",
        "window_start": "int hour (default 8)",
        "window_end": "int hour (default 17)",
        "weekdays_only": "bool (default true)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.ws = int(self.settings.get("window_start", 8))
        self.we = int(self.settings.get("window_end", 17))
        self.weekdays = self.settings.get("weekdays_only", True)
        self._tracker = ZoneTracker()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("vendor_entry")
        if not zone:
            return
        tm = _t.gmtime(ts)
        if self.weekdays and tm.tm_wday >= 5:
            return
        in_window = self.ws <= tm.tm_hour < self.we
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0, 2, 5, 7]):
            if tid is None:
                continue
            entered, _, _ = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if entered and not in_window:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Unscheduled vendor arrival",
                    detail=f"Arrival at {_t.strftime('%H:%M', tm)} outside vendor window {self.ws}:00-{self.we}:00 on {camera['name']}.",
                    frame=frame, meta={"hour": tm.tm_hour})
