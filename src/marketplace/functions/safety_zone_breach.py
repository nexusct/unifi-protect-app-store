"""Restricted-Zone Person Presence.

Reports a sustained person-class detection in a configured zone after a
debounce interval. It does not determine permission, hazard state, machine
state, or end-to-end alert timing.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "safety-zone-breach",
    "name": "Restricted-Zone Person Presence",
    "tagline": "Flags a sustained person detection in a calibrated restricted zone; alert delivery time depends on the camera, runtime, network, and routing configuration.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — restricted area",
        "hold_ms": "Detection debounce duration in milliseconds (default: 300); not an end-to-end alert-time commitment.",
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
                        title="PERSON DETECTED IN RESTRICTED ZONE",
                        detail=f"Person-class detection persisted in the configured zone on {camera['name']}; verify authorization and conditions manually.",
                        frame=frame, meta={"track": tid})
                    self._entered[key] = ts
            else:
                self._entered.pop((camera["id"], tid), None)
