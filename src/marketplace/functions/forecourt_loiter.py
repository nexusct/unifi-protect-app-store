"""Forecourt Loitering — person lingering in the forecourt after close.

After-hours person presence in the pump forecourt. C-stores deal with
late-night forecourt hanging as a safety + shrink issue; this is the
automated "move along" tripwire with clip evidence.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "forecourt-loiter",
    "name": "Forecourt Loitering Watch",
    "tagline": "Someone's been standing between the pumps for 15 minutes at 1am.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — forecourt",
        "after_hours": "[start,end] (default [23,5])",
        "loiter_minutes": "int (default 10)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hours = self.settings.get("after_hours", [23, 5])
        self.limit = float(self.settings.get("loiter_minutes", 10)) * 60
        self._tracker = ZoneTracker()
        self._alerted = set()

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("forecourt")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        s, e = int(self.hours[0]), int(self.hours[1])
        if not ((hour >= s or hour < e) if s > e else (s <= hour < e)):
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
                    title="Forecourt loitering",
                    detail=f"Person in forecourt {(ts - st['since'])/60:.0f} min after hours on {camera['name']}.",
                    frame=frame, meta={"minutes": (ts - st["since"]) / 60})
            if not st["in"]:
                self._alerted.discard(key)
