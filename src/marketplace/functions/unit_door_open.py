"""Unit Door Open — storage unit door up past the allowed window.

Roll-up door state per unit zone: open longer than a move-in visit should
be = check on it. Facilities use this for both security and the "unit left
open after auction cleanout" ops gap.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "unit-door-open",
    "name": "Storage Unit Door Watch",
    "tagline": "Flags a persistent visual open-state at a configured storage-unit door zone.",
    "category": "Security & Access",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "units": "map of unit-name → door polygon",
        "open_minutes": "int (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.limit = float(self.settings.get("open_minutes", 30)) * 60
        self._closed = {}
        self._open_since = {}

    def process(self, camera, frame, ts, ctx):
        units = (camera.get("zones") or {}).get("units") or {}
        if not units:
            return
        import cv2
        h, w = frame.shape[:2]
        for name, poly in units.items():
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
            if crop.size == 0:
                continue
            key = (camera["id"], name)
            ref = self._closed.get(key)
            if ref is None or ref.shape != crop.shape:
                self._closed[key] = crop
                continue
            diff = float(np.mean(cv2.absdiff(crop, ref))) / 255.0
            if diff > 0.08:
                self._open_since.setdefault(key, ts)
                if ts - self._open_since[key] >= self.limit:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=MANIFEST["id"],
                        title=f"Unit {name} door open {(ts - self._open_since[key])/60:.0f} min",
                        detail=f"Unit {name} door state changed {ts - self._open_since[key]:.0f}s ago on {camera['name']}.",
                        frame=frame, meta={"unit": name})
                    self._open_since[key] = ts
            else:
                self._open_since.pop(key, None)
                self._closed[key] = crop
