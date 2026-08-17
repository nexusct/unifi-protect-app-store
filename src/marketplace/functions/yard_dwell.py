"""Yard Dwell — trailer/container sitting time by zone.

How long each trailer sits in the yard before touching a dock. Yard
management systems cost five figures; this is the 80/20 from one camera.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "yard-dwell",
    "name": "Trailer Yard Dwell",
    "tagline": "Flags a trailer that remains in a configured yard row beyond the selected dwell threshold for review.",
    "category": "Manufacturing & Warehouse",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — yard area",
        "stale_hours": "int — stale trailer alert (default 72)",
    },
}

TRUCKS = (5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.stale = float(self.settings.get("stale_hours", 72)) * 3600
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("yard")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(TRUCKS)):
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, _, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"] and st["since"] and ts - st["since"] >= self.stale and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Trailer stale {(ts - st['since'])/3600:.0f}h",
                    detail=f"Truck/trailer in yard {(ts - st['since'])/3600:.1f} hours on {camera['name']}.",
                    frame=frame, meta={"hours": (ts - st["since"]) / 3600})
            if not st["in"]:
                self._alerted.discard(key)
