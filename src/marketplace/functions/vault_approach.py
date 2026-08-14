"""Vault Approach — person near the vault/safe zone without dual presence.

Cannabis vaults and back-office safes typically require two-person
presence. One person at the vault zone without a second person in frame =
compliance alert. Dispensary license audits ask for exactly this.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "vault-approach",
    "name": "Vault Two-Person Rule",
    "tagline": "One person at the vault, alone, for 90 seconds. Compliance has the clip.",
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
