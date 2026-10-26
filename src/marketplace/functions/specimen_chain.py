"""Specimen drop-zone dwell log.

Logs when a tracked person remains in the configured drop zone for the
operator-set dwell period. The signal does not confirm a deposit or custody.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "specimen-chain",
    "name": "Specimen Drop-Zone Dwell Log",
    "tagline": "Logs observed dwell events at a configured specimen-drop zone for staff review; it does not confirm a deposit or detect missing expected specimens.",
    "category": "Healthcare & Senior Living",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — specimen drop area",
        "min_dwell_seconds": "Minimum observed zone dwell before logging a possible drop event (default: 10 seconds).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.min_dwell = float(self.settings.get("min_dwell_seconds", 10))
        self._tracker = ZoneTracker()
        self._confirmed = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("drop_zone")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            key = (camera["id"], tid)
            _, dwell, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"] and st["since"] and ts - st["since"] >= self.min_dwell and key not in self._confirmed:
                self._confirmed.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Specimen-zone dwell threshold reached",
                    detail=f"Tracked-person dwell reached {ts - st['since']:.0f}s in the configured drop zone on {camera['name']}; review the event.",
                    frame=frame, meta={"dwell_s": ts - st["since"]})
            if not st["in"]:
                self._confirmed.discard(key)
