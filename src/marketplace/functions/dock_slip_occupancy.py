"""Dock Slip Occupancy — per-slip occupied/empty for marinas.

Slip zone occupied by a boat-hull-sized object, logged daily. Transient
billing verification, unauthorized liveaboard detection, and the
occupancy report harbormasters file monthly.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "dock-slip-occupancy",
    "name": "Slip Occupancy Log",
    "tagline": "Slip 22 has a boat that isn't on the register. The harbormaster has the frame.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "slips": "map of slip-name → polygon",
        "check_hour": "int (default 6)",
        "min_object_ratio": "float — boat-sized object (default 0.02)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.check_hour = int(self.settings.get("check_hour", 6))
        self.min_area = float(self.settings.get("min_object_ratio", 0.02))
        self._done_day = None

    def process(self, camera, frame, ts, ctx):
        import time as _t
        slips = (camera.get("zones") or {}).get("slips") or {}
        if not slips:
            return
        tm = _t.gmtime(ts)
        if tm.tm_hour != self.check_hour:
            return
        day = _t.strftime("%Y-%m-%d", tm)
        if self._done_day == day:
            return
        self._done_day = day
        # boats = boat class if available; fallback: large non-person objects
        boxes = boxes_of(frame)
        status = {}
        for name, poly in slips.items():
            occupied = any(
                in_zone(cx, cy, poly) and cls != "person"
                and ((x2 - x1) * (y2 - y1)) / (frame.shape[0] * frame.shape[1]) >= self.min_area
                for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes)
            status[name] = "occupied" if occupied else "empty"
        ctx.alerts.fire(
            site=ctx.site, camera=camera, detector=MANIFEST["id"],
            title="Daily slip status",
            detail=" | ".join(f"{n}: {s}" for n, s in sorted(status.items())),
            frame=frame, meta={"slips": status})
