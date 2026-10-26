"""Route-Zone Presence Log — vehicle-class detections by configured zone.

Records timestamps when a supported vehicle class is detected in each route
zone during a configured window. Vehicle identity and completed work require
review against operational records.
"""
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "route-verification",
    "name": "Route-Zone Presence Log",
    "tagline": "Records vehicle-class detections in configured route zones; verify vehicle identity and completed work against operational records.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zones": "map of route-zone → polygon",
        "window": "[start,end] hours the route should cover zones",
    },
}

VEHICLES = (2, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.window = self.settings.get("window", [2, 7])
        self._hits = {}
        self._done_day = None
        self._reported_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zones = (camera.get("zones") or {}).get("route_zones") or {}
        if not zones:
            return
        tm = site_time(ts, ctx)
        start_hour, end_hour = int(self.window[0]), int(self.window[1])
        day = _t.strftime("%Y-%m-%d", tm)
        if self._done_day != day:
            self._hits = {}
            self._done_day = day

        if start_hour <= tm.tm_hour < end_hour:
            boxes = boxes_of(frame, classes=list(VEHICLES))
            for name, poly in zones.items():
                if name in self._hits:
                    continue
                if any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes):
                    self._hits[name] = _t.strftime("%H:%M", tm)
            return

        if tm.tm_hour < end_hour or self._reported_day == day:
            return

        missing = [name for name in zones if name not in self._hits]
        ctx.alerts.fire(
            site=ctx.site, camera=camera, detector=MANIFEST["id"],
            title=f"Route-zone detections: {len(self._hits)}/{len(zones)} zones",
            detail=f"Detected: {', '.join(f'{name} {hit_time}' for name, hit_time in sorted(self._hits.items())) or 'none'}. No detection: {', '.join(missing) or 'none'}. Review route completion against operational records.",
            frame=None, meta={"covered": dict(self._hits), "missing": missing})
        self._reported_day = day
