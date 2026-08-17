"""Pen motion watch using a calibrated low-motion threshold."""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "livestock-down",
    "name": "Pen Motion Watch",
    "tagline": "Flags prolonged low motion in a configured pen for human inspection; it does not identify a down animal.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — pen area",
        "still_minutes": "int (default 45)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("still_minutes", 45)) * 60
        self._prev = None
        self._still_since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("pen")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        gray = cv2.GaussianBlur(crop, (7, 7), 0)
        if self._prev is None or self._prev.shape != gray.shape:
            self._prev = gray
            return
        diff = cv2.threshold(cv2.absdiff(gray, self._prev), 20, 255, cv2.THRESH_BINARY)[1]
        motion_ratio = float(np.count_nonzero(diff)) / diff.size
        self._prev = gray
        key = camera["id"]
        if motion_ratio < 0.002:
            self._still_since.setdefault(key, ts)
            if ts - self._still_since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Low pen motion",
                    detail=f"Low movement in the configured pen zone for {(ts - self._still_since[key])/60:.0f} min on {camera['name']}.",
                    frame=frame, meta={"still_min": (ts - self._still_since[key]) / 60})
                self._still_since[key] = ts
        else:
            self._still_since.pop(key, None)
