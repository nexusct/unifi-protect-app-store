"""Crowd Density — people-per-zone against a density cap.

Counts persons in a venue zone and fires when the count crosses the
configured density limit (event floors, school gyms, night venues).
Occupancy-code peace of mind from a camera, not a door counter.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "crowd-density",
    "name": "Crowd Density Alert",
    "tagline": "The floor crossed its density cap at 11:43pm. You knew at 11:43pm.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — venue floor",
        "max_persons": "int (default 50)",
        "hold_seconds": "int (default 20)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_n = int(self.settings.get("max_persons", 50))
        self.hold = float(self.settings.get("hold_seconds", 20))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("venue")
        if not zone:
            return
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        key = camera["id"]
        if count > self.max_n:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Crowd density {count} (cap {self.max_n})",
                    detail=f"{count} people in venue zone on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"count": count, "cap": self.max_n})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
