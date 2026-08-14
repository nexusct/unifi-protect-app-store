"""Meeting Room Usage — actual occupancy vs the booking lie.

Counts persons per meeting-room zone and logs occupied minutes per room
per day. Ends "every room is booked but they're all empty" — CRE and
workplace teams make space decisions on this.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "meeting-room-usage",
    "name": "Meeting Room Reality",
    "tagline": "Booked solid on the calendar. Empty since Tuesday. Measured.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "rooms": "map of room-name → polygon",
        "digest_hour": "int (default 18)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 18))
        self._occ = defaultdict(float)
        self._last = None
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        rooms = (camera.get("zones") or {}).get("rooms") or {}
        if not rooms:
            return
        dt = ts - (self._last or ts)
        self._last = ts
        boxes = boxes_of(frame, classes=[0])
        for name, poly in rooms.items():
            if any(in_zone(cx, cy, poly) for (_, cx, cy, *_r) in boxes):
                self._occ[name] += max(dt, 0)
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._occ:
            lines = sorted(self._occ.items(), key=lambda x: x[1], reverse=True)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Meeting room usage today",
                detail=" | ".join(f"{n}: {v/60:.0f} min occupied" for n, v in lines),
                frame=None, meta={"occupied_min": {n: round(v / 60, 1) for n, v in lines}})
            self._occ.clear()
            self._last_day = day
