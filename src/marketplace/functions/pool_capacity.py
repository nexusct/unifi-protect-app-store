"""Pool-area person count vs configured review threshold.

Counts person detections in a configured pool/deck zone. The estimate does
not establish actual occupancy or compliance with a posted limit.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pool-capacity",
    "name": "Pool-Area Person Count",
    "tagline": "Counts detected people in a calibrated pool and deck zone and flags sustained counts above a configured review threshold.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pool + deck",
        "max_bathers": "int (default 20)",
        "hold_seconds": "int (default 45)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_n = int(self.settings.get("max_bathers", 20))
        self.hold = float(self.settings.get("hold_seconds", 45))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pool")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_n:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Pool-area count estimate {count} (review threshold {self.max_n})",
                    detail=f"Detected-person count {count} exceeded the configured review threshold on {camera['name']}; verify manually.",
                    frame=frame, meta={"count": count})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
