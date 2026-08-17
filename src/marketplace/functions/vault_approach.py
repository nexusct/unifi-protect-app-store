"""Solo person detection near a configured vault/safe zone.

Flags sustained single-person presence in the configured zone when no second
person detection appears in the frame. It does not determine policy compliance.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "vault-approach",
    "name": "Solo Vault-Zone Dwell Alert",
    "tagline": "Flags a single detected person who remains in the configured vault zone beyond the review threshold; saves a local alert snapshot for review.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — vault approach",
        "solo_seconds": "int (default 90)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("solo_seconds", 90))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("vault")
        if not zone:
            return
        boxes = boxes_of(frame, classes=[0])
        in_vault = [b for b in boxes if in_zone(b[1], b[2], zone)]
        key = camera["id"]
        if len(in_vault) == 1 and len(boxes) == 1:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Solo vault presence",
                    detail=f"Single person at vault zone {ts - self._since[key]:.0f}s with no second person on {camera['name']}.",
                    frame=frame, meta={"solo_s": ts - self._since[key]})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
