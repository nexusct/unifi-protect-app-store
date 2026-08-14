"""Fuel Dock Dwell — boat camping at the fuel dock past the window.

Fuel docks are throughput businesses. A boat sitting past the fueling
window blocks the line; the dockhand gets the alert with the dwell time.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "fuel-dock-dwell",
    "name": "Fuel Dock Dwell",
    "tagline": "That boat's been on the fuel dock 45 minutes. The line is three deep.",
    "category": "Intelligence",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — fuel dock",
        "max_minutes": "int (default 25)",
        "min_object_ratio": "float (default 0.02)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("max_minutes", 25)) * 60
        self.min_area = float(self.settings.get("min_object_ratio", 0.02))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("fuel_dock")
        if not zone:
            return
        occupied = any(
            in_zone(cx, cy, zone) and cls != "person"
            and ((x2 - x1) * (y2 - y1)) / (frame.shape[0] * frame.shape[1]) >= self.min_area
            for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame))
        key = camera["id"]
        if occupied:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Fuel dock occupied {(ts - self._since[key])/60:.0f} min",
                    detail=f"Boat at fuel dock past window on {camera['name']}.",
                    frame=frame, meta={"minutes": (ts - self._since[key]) / 60})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
