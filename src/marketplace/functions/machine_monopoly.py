"""Machine-Row Dwell — tracked person presence beyond a threshold.

Reports when a person-class track remains in the configured machine-row zone.
It does not determine machine usage, obstruction, or customer behavior.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "machine-monopoly",
    "name": "Machine-Row Dwell Watch",
    "tagline": "Flags a person-class track remaining in a configured machine-row zone beyond the dwell threshold.",
    "category": "Retail & QSR",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — machine row approach",
        "dwell_minutes": "int (default 40)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("dwell_minutes", 40)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("machine_row")
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
                    title=f"Machine-row dwell {(ts - st['since'])/60:.0f} min",
                    detail=f"Person-class track remained in the machine-row zone on {camera['name']} past the configured dwell threshold.",
                    frame=frame, meta={"minutes": (ts - st["since"]) / 60})
            if not st["in"]:
                self._alerted.discard(key)
