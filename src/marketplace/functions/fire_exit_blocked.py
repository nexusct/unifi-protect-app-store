"""Egress-Zone Object Dwell — object detection persists in a configured zone.

An object-class detection that persists in a configured egress zone produces
a staff review alert. It does not determine code or regulatory compliance.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "fire-exit-blocked",
    "name": "Egress-Zone Object Review",
    "tagline": "Flags a persistent object in a configured egress zone for staff review.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — egress area",
        "blocked_seconds": "Object-dwell review threshold in seconds (default 60)",
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
            if cls != 0 and in_zone(cx, cy, zone):
                blocking = True
                break
        key = camera["id"]
        if blocking:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Persistent object in egress zone",
                    detail=f"Object-class detection persisted in the configured egress zone on {camera['name']} for {ts - self._since[key]:.0f}s; verify clearance manually.",
                    frame=frame, meta={"blocked_s": ts - self._since[key]})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
