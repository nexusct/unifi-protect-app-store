"""Child Safety Zone — small person in a restricted area.

Height-proxy filtering (bbox height vs adult reference in frame) catches
small persons entering pools, machinery areas, rooftops, or parking
drives. Daycares, schools, multi-family, and hospitality all have this
liability.
"""
from marketplace.contract import MarketplaceFunction, boxes_of, in_zone

MANIFEST = {
    "id": "child-safety-zone",
    "name": "Child Safety Zone",
    "tagline": "A small person near the pool gate at 9pm. Phone alert, right now.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — restricted area",
        "max_height_ratio": "float — child height proxy vs frame (default 0.35)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.max_h = float(self.settings.get("max_height_ratio", 0.35))
        self._alerted = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("restricted")
        if not zone:
            return
        h = frame.shape[0]
        for (cls, cx, cy, x1, y1, x2, y2, tid) in boxes_of(frame, classes=[0]):
            if tid is None or not in_zone(cx, cy, zone):
                continue
            height_ratio = (y2 - y1) / h
            if height_ratio <= self.max_h and ts - self._alerted.get(tid, 0) > 120:
                self._alerted[tid] = ts
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Small person in restricted zone",
                    detail=f"Child-height figure (h ratio {height_ratio:.2f}) in restricted zone on {camera['name']}.",
                    frame=frame, meta={"height_ratio": round(height_ratio, 3)})
