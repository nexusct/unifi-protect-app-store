"""Two-Person Rule — configured dual-presence zone monitoring.

Person count in the server-room zone: exactly one person present beyond
the threshold produces a policy-review alert and supporting event record.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "two-person-rule",
    "name": "Solo Server-Room Dwell Alert",
    "tagline": "Flags sustained solo occupancy in a configured server-room zone for policy review; it does not establish SOC 2, PCI, or other compliance.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "Polygon for the server-room area to monitor.",
        "solo_seconds": "Seconds of sustained solo occupancy before review (default 240).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("solo_seconds", 240))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("server_room")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count == 1:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Solo presence in server room",
                    detail=f"Single person in server room for {ts - self._since[key]:.0f}s on {camera['name']}.",
                    frame=frame, meta={"solo_s": ts - self._since[key]})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
