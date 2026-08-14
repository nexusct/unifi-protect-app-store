"""Specimen Chain-of-Custody — lab-drop zone handoff verification.

Tracks person approaching the specimen drop zone and staying long enough
to deposit (dwell ≥ N seconds), logging each handoff with a timestamp.
Missing expected handoffs = the audit gap labs get cited for.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "specimen-chain",
    "name": "Specimen Drop Verification",
    "tagline": "Every drop logged with a timestamp. Every missing one flagged.",
    "category": "Healthcare & Senior Living",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — specimen drop area",
        "min_dwell_seconds": "int — deposit confirmation dwell (default 10)",
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
                    title="Specimen drop confirmed",
                    detail=f"Deposit dwell {ts - st['since']:.0f}s at drop zone on {camera['name']}.",
                    frame=frame, meta={"dwell_s": ts - st["since"]})
            if not st["in"]:
                self._confirmed.discard(key)
