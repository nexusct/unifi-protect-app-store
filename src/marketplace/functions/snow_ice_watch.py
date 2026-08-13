"""Snow & Ice Watch — entrance coverage detection.

Bright/white coverage ratio at entrances and walks over threshold = snow
accumulation needing clearing. Slip-fall claims start at the front walk;
so does the documentation that you maintained it.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "snow-ice-watch",
    "name": "Snow & Ice Watch",
    "tagline": "White walk at 6am, crew dispatched by 6:05. Documentation included.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — walk/entrance",
        "white_ratio": "float (default 0.45)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("white_ratio", 0.45))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("walk")
        if not zone:
            return
        import cv2
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = hsv[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)]
        if crop.size == 0:
            return
        white = cv2.inRange(crop, (0, 0, 190), (180, 45, 255))
        ratio = float(np.count_nonzero(white)) / white.size
        key = camera["id"]
        if ratio >= self.limit:
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= 300:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Snow/ice accumulation at entrance",
                    detail=f"White coverage {ratio:.0%} on {camera['name']} for 5+ minutes.",
                    frame=frame, meta={"coverage": round(ratio, 3)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
