"""Safety Zone Breach — person inside a restricted machine zone.

Interlock-by-camera: person enters a defined danger zone (press cell,
robot envelope, conveyor pit) and the alert fires immediately. Optional
machine-active gating via a bright status-light region check.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "safety-zone-breach",
    "name": "Safety Zone Breach",
    "tagline": "Person in the press cell. Alert in under a second.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — restricted area",
        "hold_ms": "int — debounce (default 300)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._entered = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("restricted")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if in_zone(cx, cy, zone):
                key = (camera["id"], tid)
                self._entered.setdefault(key, ts)
                if ts - self._entered[key] >= float(self.settings.get("hold_ms", 300)) / 1000:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title="RESTRICTED ZONE BREACH",
                        detail=f"Person inside restricted zone on {camera['name']}.",
                        frame=frame, meta={"track": tid})
                    self._entered[key] = ts
            else:
                self._entered.pop((camera["id"], tid), None)
