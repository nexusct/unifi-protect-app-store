"""Ice Cooler Stock — outdoor cooler empty/lean visual state.

Compares the ice-cooler zone's visual fullness (edge density from bag
texture) against a stocked baseline. Empty ice coolers on a hot Saturday
are pure lost margin and nobody checks them.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "ice-cooler-stock",
    "name": "Ice Cooler Stock Watch",
    "tagline": "Flags a drop in cooler-face texture relative to a stocked baseline; alert delivery depends on routing settings.",
    "category": "Retail & QSR",
    "tier": "starter",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — cooler face",
        "drop_ratio": "float vs stocked baseline (default 0.4)",
        "check_minutes": "int — check cadence (default 30)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.drop = float(self.settings.get("drop_ratio", 0.4))
        self.cadence = float(self.settings.get("check_minutes", 30)) * 60
        self._baseline = None
        self._samples = []
        self._last_check = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("cooler")
        if not zone:
            return
        key = camera["id"]
        if ts - self._last_check.get(key, 0) < self.cadence:
            return
        self._last_check[key] = ts
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        density = float(np.count_nonzero(cv2.Canny(crop, 50, 150))) / crop.size
        if self._baseline is None:
            self._samples.append(density)
            if len(self._samples) >= 12:
                self._baseline = float(np.mean(self._samples))
            return
        if self._baseline > 0 and (self._baseline - density) / self._baseline >= self.drop:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Ice cooler low or empty",
                detail=f"Cooler fullness dropped {(self._baseline - density)/self._baseline:.0%} vs baseline on {camera['name']}.",
                frame=frame, meta={"density": round(density, 4)})
