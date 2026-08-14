"""Route Verification — service vehicle present in each zone on schedule.

Street sweepers, snow plows, waste routes: did the vehicle actually cover
each zone in its window? Municipal contractors prove service delivery
with zone timestamps instead of driver logs.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "route-verification",
    "name": "Service Route Verification",
    "tagline": "The sweeper hit zone 12 at 4:40am. Proven, timestamped, done.",
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

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zones = (camera.get("zones") or {}).get("route_zones") or {}
        if not zones:
            return
        tm = _t.gmtime(ts)
        if not (int(self.window[0]) <= tm.tm_hour < int(self.window[1])):
            return
        day = _t.strftime("%Y-%m-%d", tm)
        if self._done_day != day:
            self._hits = {}
            self._done_day = day
        boxes = boxes_of(frame, classes=list(VEHICLES))
        for name, poly in zones.items():
            if name in self._hits:
                continue
            if any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes):
                self._hits[name] = _t.strftime("%H:%M", tm)
        if tm.tm_hour == int(self.window[1]) - 1 and self._hits:
            missing = [n for n in zones if n not in self._hits]
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Route coverage: {len(self._hits)}/{len(zones)} zones",
                detail=f"Covered: {', '.join(f'{n} {t}' for n, t in sorted(self._hits.items()))}. Missing: {', '.join(missing) or 'none'}.",
                frame=None, meta={"covered": dict(self._hits), "missing": missing})
