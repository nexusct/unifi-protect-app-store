"""Two-Person Rule — server-room access always in pairs.

Person count in the server-room zone: exactly one person present beyond
the threshold = policy violation alert. SOC 2 and PCI physical controls
often mandate dual presence; this produces the evidence.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "two-person-rule",
    "name": "Two-Person Rule",
    "tagline": "One person in the server room for 4 minutes. SOC 2 auditor never sees it — you already fixed it.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — server room",
        "solo_seconds": "int (default 240)",
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
