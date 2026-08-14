"""Thermal Shimmer — heat-plume visual signature near rack exhausts.

Heat shimmer shows as high-frequency pixel variance in the exhaust zone.
A new shimmer pattern where none should be = a cooling problem developing
before the temp sensors move. The cheap early-warning layer for MDFs.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "thermal-shimmer",
    "name": "Thermal Shimmer Watch",
    "tagline": "The exhaust plume changed shape at 2pm. The temp sensor noticed at 2:40.",
    "category": "Intelligence",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — exhaust area",
        "variance_shift": "float — vs baseline (default 0.5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.shift = float(self.settings.get("variance_shift", 0.5))
        self._baseline = {}
        self._samples = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("exhaust")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        # shimmer proxy: high-frequency content via Laplacian variance
        var = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        key = camera["id"]
        self._samples.setdefault(key, []).append(var)
        if len(self._samples[key]) < 60:
            return
        base = float(np.mean(self._samples[key][-60:]))
        if base > 0 and abs(var - base) / base >= self.shift:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Thermal signature changed",
                detail=f"Exhaust-zone variance {var:.0f} vs baseline {base:.0f} on {camera['name']}.",
                frame=frame, meta={"variance": round(var, 1), "baseline": round(base, 1)})
            self._samples[key] = [var]  # reset around new state after alert
