"""Crematory Access Log — every entry to the restricted crematory zone.

Restricted-area access with timestamps and clips. Crematory compliance
requires strict access control; this produces the access log as evidence.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "crematory-access",
    "name": "Crematory Access Log",
    "tagline": "Every entry to the crematory, timestamped, with a clip. The log writes itself.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — crematory door approach",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self._tracker = ZoneTracker()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("crematory")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            entered, _, _ = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if entered:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Crematory zone entry",
                    detail=f"Person entered crematory approach on {camera['name']}.",
                    frame=frame, meta={"track": tid})
