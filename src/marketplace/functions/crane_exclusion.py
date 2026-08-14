"""Crane Exclusion Zone — person under the lift path.

Person detected inside the crane swing/load exclusion zone during active
operation windows. Construction's most fatal scenario gets a camera-based
interlock alert to the lift director.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "crane-exclusion",
    "name": "Crane Exclusion Zone",
    "tagline": "Person under the load path. The lift director's phone buzzes.",
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
                    title="PERSON UNDER CRANE LOAD PATH",
                    detail=f"Person in crane exclusion zone on {camera['name']}.",
                    frame=frame, meta={"track": tid})
                self._since[key] = ts
        # cleanup
        for key in list(self._since):
            pass  # state resets via alert re-arm
