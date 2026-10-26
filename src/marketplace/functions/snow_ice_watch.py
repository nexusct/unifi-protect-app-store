"""Bright, low-saturation walkway-coverage watch.

Flags a sustained pixel-coverage proxy for inspection. It does not identify
snow or ice and does not document maintenance activity.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "snow-ice-watch",
    "name": "White-Coverage Walkway Watch",
    "tagline": "Flags sustained bright, low-saturation coverage in a configured walkway zone for inspection; it does not confirm ice or crew dispatch.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — walk/entrance",
        "white_ratio": "Bright/white pixel-coverage threshold; this is a visual proxy and does not identify ice.",
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
                    title="Sustained bright walkway coverage",
                    detail=f"Bright, low-saturation coverage measured {ratio:.0%} on {camera['name']} for 5+ minutes; inspect the area to determine the cause.",
                    frame=frame, meta={"coverage": round(ratio, 3)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
