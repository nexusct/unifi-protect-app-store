"""Magnet Crane Exclusion — person in the magnet/crane swing zone.

Scrap magnet cranes and yard cranes kill people who wander under them.
Person in the exclusion zone while the crane zone shows activity =
immediate alert. Same physics as construction crane exclusion, tuned for
yard operations.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "magnet-crane-exclusion",
    "name": "Magnet Crane Exclusion",
    "tagline": "Person under the magnet while it's live. The operator's cab buzzer fires.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — exclusion area under crane/magnet path",
        "hold_ms": "int (default 400)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hold = float(self.settings.get("hold_ms", 400)) / 1000
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
                    title="PERSON IN CRANE EXCLUSION ZONE",
                    detail=f"Person under magnet/crane path on {camera['name']}.",
                    frame=frame, meta={"track": tid})
                self._since[key] = ts
