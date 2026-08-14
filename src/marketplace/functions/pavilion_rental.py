"""Pavilion Rental Verify — park pavilion occupancy vs rental schedule.

Is the rented pavilion actually in use during its rental window? Is an
unrented pavilion occupied by a walk-up group? Park districts bill and
enforce on this.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "pavilion-rental",
    "name": "Pavilion Rental Verification",
    "tagline": "Pavilion 2 is packed and nobody rented it. Or it's rented and empty. Either way, logged.",
    "category": "Compliance",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pavilion",
        "rental_windows": "[[start,end],...] hours rented (default [])",
        "min_persons": "int — occupied threshold (default 4)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.windows = self.settings.get("rental_windows", [])
        self.min_n = int(self.settings.get("min_persons", 4))
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        zone = (camera.get("zones") or {}).get("pavilion")
        if not zone:
            return
        hour = int(_t.strftime("%H", _t.gmtime(ts)))
        rented = any(int(w[0]) <= hour < int(w[1]) for w in self.windows)
        count = sum(1 for (_, cx, cy, *_r) in boxes_of(frame, classes=[0]) if in_zone(cx, cy, zone))
        occupied = count >= self.min_n
        key = camera["id"]
        if occupied and not rented and ts - self._alerted.get(key, 0) > 3600:
            self._alerted[key] = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Pavilion occupied without rental",
                detail=f"{count} people in pavilion outside rental windows on {camera['name']}.",
                frame=frame, meta={"persons": count})
