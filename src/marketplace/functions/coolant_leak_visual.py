"""Coolant/Water Leak — pooling growth near CRAC/pipe zones.

A dark reflective patch that grows in the floor zone = a leak forming.
Water in a data room is a five-figure minute; this catches the puddle
while it's a mop job, not a remediation.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "coolant-leak-visual",
    "name": "Dark Floor-Region Change",
    "tagline": "Flags growth in dark pixels relative to a learned floor-zone baseline; inspect for leaks, shadows, or scene changes.",
    "category": "Property & Liability",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — floor area near equipment",
        "growth_ratio": "float — dark-region growth (default 0.03)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.growth = float(self.settings.get("growth_ratio", 0.03))
        self._baseline = {}
        self._samples = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("floor")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        dark = float(np.count_nonzero(cv2.inRange(crop, 0, 45))) / crop.size
        key = camera["id"]
        self._samples.setdefault(key, []).append(dark)
        if len(self._samples[key]) < 30:
            return
        base = float(np.mean(self._samples[key][:30]))
        if dark - base >= self.growth:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Possible leak pooling",
                detail=f"Dark floor region grew {(dark - base):.1%} over baseline on {camera['name']}.",
                frame=frame, meta={"dark_ratio": round(dark, 3), "baseline": round(base, 3)})
