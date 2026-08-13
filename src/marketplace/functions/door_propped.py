"""Door Propped Open — door zone stuck in motion/open state too long.

Watches a door zone's motion energy: normal cycles spike and settle;
propped doors keep a persistent change vs the closed reference. Pairs
with Access door-held events but works on doors with no sensors at all.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "door-propped",
    "name": "Door Propped Open",
    "tagline": "The back door propped for a smoke break is your inventory walking out.",
    "category": "Property & Liability",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — door area",
        "propped_seconds": "int (default 90)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("propped_seconds", 90))
        self._closed = {}
        self._open_since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("door")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        if key not in self._closed:
            self._closed[key] = crop  # assume starts closed
            return
        diff = float(np.mean(cv2.absdiff(crop, self._closed[key]))) / 255.0
        if diff > 0.06:  # state differs from closed reference
            self._open_since.setdefault(key, ts)
            if ts - self._open_since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Door propped open",
                    detail=f"Door zone changed state {ts - self._open_since[key]:.0f}s ago on {camera['name']}.",
                    frame=frame, meta={"open_s": ts - self._open_since[key]})
                self._open_since[key] = ts
        else:
            self._open_since.pop(key, None)
            self._closed[key] = crop  # slow-adapt the closed reference
