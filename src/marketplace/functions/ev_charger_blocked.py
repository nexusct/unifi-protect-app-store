"""EV Charger Blocked — stall occupied past charge time / by non-EVs.

Dwell tracking on EV charging stalls. Vehicle parked past the configured
charge window (or a day-long camper) triggers a move-along alert. EV
amenity ROI dies when stalls are blocked all day.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "ev-charger-blocked",
    "name": "EV Charger Blocked",
    "tagline": "The stall is for charging, not all-day parking.",
    "category": "Automotive & Parking",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — EV stall",
        "max_minutes": "int — allowed dwell (default 120)",
    },
}

VEHICLES = (2, 3, 5, 7)


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("max_minutes", 120)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("ev_stall")
        if not zone:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=list(VEHICLES)):
            if tid is None:
                continue
            key = (camera["id"], tid)
            entered, dwell, st = self._tracker.update(key, in_zone(cx, cy, zone), ts)
            if st["in"] and st["since"] and ts - st["since"] >= self.limit and key not in self._alerted:
                self._alerted.add(key)
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="EV stall blocked",
                    detail=f"Vehicle parked {(ts - st['since'])/60:.0f} min in EV stall on {camera['name']}.",
                    frame=frame, meta={"dwell_min": (ts - st['since']) / 60})
            if not st["in"]:
                self._alerted.discard(key)
