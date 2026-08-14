"""Change Machine Watch — long dwell + repeated motion at the machine.

Break-in attempts on change machines have a signature: one person, long
dwell, repeated jerky motion at the machine face. Not proof — a heads-up
with a clip before the machine is emptied or opened.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "change-machine-watch",
    "name": "Change Machine Watch",
    "tagline": "Twenty minutes at the change machine at 4am. That's not laundry.",
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
