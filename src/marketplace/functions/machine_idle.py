"""Machine-zone motion-energy summary from frame differences."""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "machine-idle",
    "name": "Machine-Zone Motion-Energy Summary",
    "tagline": "Estimates the share of analyzed frames with motion above a calibrated threshold in each configured machine zone; it does not verify machine operation.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "machines": "Map of machine-zone names to normalized polygons.",
        "motion_threshold": "Frame-difference energy threshold for high-motion classification (default 0.02).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.thresh = float(self.settings.get("motion_threshold", 0.02))
        self._prev = {}
        self._active = {}
        self._total = {}

    def process(self, camera, frame, ts, ctx):
        import cv2
        machines = (camera.get("zones") or {}).get("machines") or {}
        if not machines:
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        for name, poly in machines.items():
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            x1, x2 = int(min(xs) * w), int(max(xs) * w)
            y1, y2 = int(min(ys) * h), int(max(ys) * h)
            crop = gray[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            key = (camera["id"], name)
            prev = self._prev.get(key)
            self._prev[key] = crop
            if prev is None or prev.shape != crop.shape:
                continue
            energy = float(np.mean(cv2.absdiff(crop, prev))) / 255.0
            self._total[key] = self._total.get(key, 0) + 1
            if energy > self.thresh:
                self._active[key] = self._active.get(key, 0) + 1
            total = self._total[key]
            if total and total % 3600 == 0:  # ~hourly at 1fps
                pct = 100 * self._active.get(key, 0) / total
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title=f"{name}: {pct:.0f}% high-motion frames",
                    detail=f"Configured zone {name} on {camera['name']} exceeded the motion-energy threshold in {pct:.0f}% of analyzed frames.",
                    frame=None, meta={"machine": name, "high_motion_pct": round(pct, 1)})
