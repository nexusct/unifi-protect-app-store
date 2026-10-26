"""Housekeeping Pace — room-entry to room-exit per unit.

Tracks housekeeper entry/exit at room doors: rooms cleaned per shift and
minutes per room. Hotel housekeeping is the margin line — this is its
measurement, no wearable badges required.
"""
from collections import defaultdict
from marketplace.contract import site_time, MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "housekeeping-pace",
    "name": "Housekeeping Pace Tracker",
    "tagline": "Summarizes observed visits and dwell intervals at configured room-door zones.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "room_doors": "map of room-name → door polygon",
        "digest_hour": "int (default 16)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.digest_hour = int(self.settings.get("digest_hour", 16))
        self._inside = {}
        self._times = defaultdict(list)
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        doors = (camera.get("zones") or {}).get("room_doors") or {}
        if not doors:
            return
        for (cls, cx, cy, *rest, tid) in boxes_of(frame, classes=[0]):
            if tid is None:
                continue
            for room, poly in doors.items():
                inside = in_zone(cx, cy, poly)
                key = (camera["id"], tid, room)
                if inside and key not in self._inside:
                    self._inside[key] = ts
                elif not inside and key in self._inside:
                    self._times[room].append(ts - self._inside.pop(key))
        tm = site_time(ts, ctx)
        day = _t.strftime("%Y-%m-%d", tm)
        if tm.tm_hour == self.digest_hour and self._last_day != day and self._times:
            total_rooms = sum(len(v) for v in self._times.values())
            avg = sum(sum(v) for v in self._times.values()) / max(total_rooms, 1)
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title=f"Housekeeping: {total_rooms} rooms, {avg/60:.0f} min avg",
                detail=f"{total_rooms} room visits today on {camera['name']}, average {avg/60:.1f} minutes.",
                frame=None, meta={"rooms": total_rooms, "avg_minutes": round(avg / 60, 1)})
            self._times.clear()
            self._last_day = day
