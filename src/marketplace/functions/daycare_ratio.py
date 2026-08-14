"""Daycare Ratio — children-per-staff count in room zones.

License ratios (e.g. 4:1 infants, 8:1 toddlers) are enforced by state.
This counts child-height vs adult-height figures per room zone and alerts
when the ratio crosses the configured limit.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "daycare-ratio",
    "name": "Classroom Ratio Watch",
    "tagline": "9 toddlers, 1 adult, room 3. Ratio alert before the licensor arrives.",
    "category": "Compliance",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — classroom",
        "max_ratio": "float — children per adult (default 8)",
        "child_height_ratio": "float — child proxy (default 0.38)",
        "hold_seconds": "int (default 120)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_ratio = float(self.settings.get("max_ratio", 8))
        self.child_h = float(self.settings.get("child_height_ratio", 0.38))
        self.hold = float(self.settings.get("hold_seconds", 120))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("classroom")
        if not zone:
            return
        h = frame.shape[0]
        children = adults = 0
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if not in_zone(cx, cy, zone):
                continue
            if (y2 - y1) / h <= self.child_h:
                children += 1
            else:
                adults += 1
        key = camera["id"]
        ratio = children / max(adults, 1) if children else 0
        if children and ratio > self.max_ratio:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"Ratio {ratio:.1f}:1 in classroom",
                    detail=f"{children} children / {adults} adults on {camera['name']} for {ts - self._since[key]:.0f}s.",
                    frame=frame, meta={"children": children, "adults": adults, "ratio": round(ratio, 1)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
