"""Restricted-zone entry log for a configured approach."""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "crematory-access",
    "name": "Restricted-Zone Entry Log",
    "tagline": "Logs detected person entries to a configured restricted approach with timestamps and local alert snapshots for review.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "Polygon for the restricted door approach to monitor.",
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
                    title="Restricted-zone entry",
                    detail=f"Detected person entered the configured restricted approach on {camera['name']}.",
                    frame=frame, meta={"track": tid})
