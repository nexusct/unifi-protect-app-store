"""Fuel-dock large-object dwell estimate.

Flags a sufficiently large non-person detection that persists in the configured
fuel-dock zone. Operators verify whether the detection represents a vessel.
"""
from marketplace.contract import MarketplaceFunction, ZoneTracker, boxes_of, in_zone

MANIFEST = {
    "id": "fuel-dock-dwell",
    "name": "Fuel Dock Dwell",
    "tagline": "Flags sustained large non-person detections in a configured fuel-dock zone; operators verify vessel presence.",
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
            in_zone(cx, cy, zone) and cls != 0
            and (x2 - x1) * (y2 - y1) >= self.min_area
            for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame))
        key = camera["id"]
        if occupied:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Fuel-dock object dwell {(ts - self._since[key])/60:.0f} min",
                    detail=f"Large non-person detection persisted in the fuel-dock zone on {camera['name']}; verify vessel presence.",
                    frame=frame, meta={"minutes": (ts - self._since[key]) / 60})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
