"""Rack Door Open — server cabinet/row door state monitoring.

Cabinet or row-door zone changed from closed reference beyond the window.
Colo and enterprise server rooms bill on access discipline; this is the
visual audit layer over the badge log.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "rack-door-open",
    "name": "Rack Door Watch",
    "tagline": "Cabinet 14's door has been open for 20 minutes. The badge log says nobody.",
    "category": "Security & Access",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — cabinet/row door",
        "open_minutes": "int (default 15)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("open_minutes", 15)) * 60
        self._closed = {}
        self._open_since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("rack_door")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        ref = self._closed.get(key)
        if ref is None or ref.shape != crop.shape:
            self._closed[key] = crop
            return
        diff = float(np.mean(cv2.absdiff(crop, ref))) / 255.0
        if diff > 0.07:
            self._open_since.setdefault(key, ts)
            if ts - self._open_since[key] >= self.limit:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Rack door open past window",
                    detail=f"Cabinet door zone changed {(ts - self._open_since[key])/60:.0f} min ago on {camera['name']}.",
                    frame=frame, meta={"open_min": (ts - self._open_since[key]) / 60})
                self._open_since[key] = ts
        else:
            self._open_since.pop(key, None)
            self._closed[key] = cv2.addWeighted(ref, 0.99, crop, 0.01, 0)
