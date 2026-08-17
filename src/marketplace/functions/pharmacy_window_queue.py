"""Pharmacy Pickup-Zone Queue Estimate.

Counts concurrent person-class detections in a configured pickup zone and
estimates dwell for tracker IDs while observed. It does not identify people,
determine service state, or guarantee continuous tracking.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "pharmacy-window-queue",
    "name": "Pharmacy Pickup-Zone Queue Estimate",
    "tagline": "Estimates pickup-zone person count and observed tracker dwell for operational review.",
    "category": "Healthcare & Senior Living",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pickup line area",
        "max_line": "int (default 5)",
        "wait_alert_minutes": "int (default 15)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_line = int(self.settings.get("max_line", 5))
        self.wait_alert = float(self.settings.get("wait_alert_minutes", 15)) * 60
        self._tracker = ZoneTracker()
        self._waits = []
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pickup")
        if not zone:
            return
        present = set()
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            entered, dwell, st = self._tracker.update((camera["id"], tid), in_zone(cx, cy, zone), ts)
            if st["in"]:
                present.add(tid)
                if st["since"] and ts - st["since"] >= self.wait_alert and tid not in self._alerted:
                    self._alerted.add(tid)
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Pickup-zone track dwell {(ts - st['since'])/60:.0f} min",
                        detail=f"A person-class track remained in the pickup zone past the {self.wait_alert/60:.0f} min review threshold on {camera['name']}.",
                        frame=frame, meta={"wait_min": (ts - st['since']) / 60})
            elif tid in self._alerted:
                self._alerted.discard(tid)
        if len(present) > self.max_line:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Pickup-zone count at {len(present)}",
                detail=f"Observed person-track count {len(present)} exceeds the configured threshold {self.max_line} on {camera['name']}.",
                frame=frame, meta={"line": len(present)})
