"""Change-machine zone dwell watch.

Flags extended person-track dwell in the configured approach zone. It does
not determine tampering or intent and can attach an optional JPEG snapshot.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "change-machine-watch",
    "name": "Change Machine Watch",
    "tagline": "Flags extended person dwell at a configured change-machine zone during selected hours.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — change machine approach",
        "dwell_minutes": "int (default 12)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("dwell_minutes", 12)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("change_machine")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, _, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"] and st["since"] and ts - st["since"] >= self.limit and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Extended change-machine dwell",
                    detail=f"Person at change machine {(ts - st['since'])/60:.0f} min on {camera['name']}.",
                    frame=frame, meta={"minutes": (ts - st["since"]) / 60})
            if not st["in"]:
                self._alerted.discard(key)
