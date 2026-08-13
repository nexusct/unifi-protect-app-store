"""Fire Exit Blocked — object camped in an egress zone.

Any non-person object stationary in a fire-exit zone past the threshold
fires a code-compliance alert. The single most-cited OSHA/insurance
violation in warehouses — and the cheapest to prevent.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "fire-exit-blocked",
    "name": "Fire Exit Blocked",
    "tagline": "A pallet in front of the fire exit is a five-figure fine. Not anymore.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — egress area",
        "blocked_seconds": "int (default 60)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("blocked_seconds", 60))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("exit")
        if not zone:
            return
        blocking = False
        for (cls, cx, cy, *rest, tid) in boxes_of(frame):
            if cls != "person" and in_zone(cx, cy, zone):
                blocking = True
                break
        key = camera["id"]
        if blocking:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Fire exit blocked",
                    detail=f"Object in egress zone on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"blocked_s": ts - self._since[key]})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
