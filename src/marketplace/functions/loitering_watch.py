"""Loitering Watch — person stationary in a watch zone past threshold.

Perimeter fences, ATM vestibules, after-hours storefronts: a person who
stays in the zone beyond the limit fires a check-it-out alert with the
dwell time. The classic loss-prevention and premise-safety trigger.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "loitering-watch",
    "name": "Loitering Watch",
    "tagline": "Still there after 10 minutes. Someone should take a look.",
    "category": "People & Safety",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — watch area",
        "loiter_minutes": "int (default 10)",
        "active_hours": "[start,end] optional",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("loiter_minutes", 10)) * 60
        self.hours = self.settings.get("active_hours")
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        if self.hours:
            hour = int(_t.strftime("%H", _t.gmtime(ts)))
            s, e = int(self.hours[0]), int(self.hours[1])
            if not ((hour >= s or hour < e) if s > e else (s <= hour < e)):
                return
        zone = (camera.get("zones") or {}).get("watch")
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
                    title=f"Loitering {(ts - st['since'])/60:.0f} min",
                    detail=f"Person stationary in watch zone on {camera['name']} for {(ts - st['since'])/60:.0f} minutes.",
                    frame=frame, meta={"dwell_min": (ts - st['since']) / 60})
            if not st["in"]:
                self._alerted.discard(key)
