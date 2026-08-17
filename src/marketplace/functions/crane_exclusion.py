"""Crane exclusion-zone person-presence signal.

Flags a person detection inside the configured exclusion polygon. Camera
analysis does not determine crane, load, or operating state.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "crane-exclusion",
    "name": "Crane Exclusion-Zone Presence Alert",
    "tagline": "Flags a person detected in a calibrated crane exclusion zone; verify operating state and alert routing through site procedures.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — exclusion area under/near crane",
        "hold_ms": "int (default 500)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hold = float(self.settings.get("hold_ms", 500)) / 1000
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("exclusion")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            key = (camera["id"], tid)
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Person detected in configured crane exclusion zone",
                    detail=f"Person track remained in the configured exclusion zone on {camera['name']}; verify crane and load state through site procedures.",
                    frame=frame, meta={"track": tid})
                self._since[key] = ts
        # cleanup
        for key in list(self._since):
            pass  # state resets via alert re-arm
