"""Play Yard Cluster — sudden multi-animal motion cluster (fight proxy).

Rapid simultaneous high-motion across the play-yard zone = likely
scuffle. Daycare staff get an immediate "check the yard" alert with the
clip — the difference between a scuffle and a vet bill.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "play-yard-cluster",
    "name": "Play Yard Scuffle Alert",
    "tagline": "Sudden chaos in the yard. Staff alerted in seconds, clip attached.",
    "category": "People & Safety",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — play yard",
        "energy_spike": "float — vs rolling baseline (default 3.0)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.spike = float(self.settings.get("energy_spike", 3.0))
        self._prev = {}
        self._baseline = {}
        self._cooldown = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("yard")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        prev = self._prev.get(key)
        self._prev[key] = crop
        if prev is None or prev.shape != crop.shape:
            return
        e = float(np.mean(cv2.absdiff(crop, prev))) / 255.0
        base = self._baseline.get(key, e or 0.01)
        self._baseline[key] = 0.99 * base + 0.01 * e  # slow-adapting normal
        if e > max(base, 0.01) * self.spike and ts - self._cooldown.get(key, 0) > 60:
            self._cooldown[key] = ts
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Play yard activity spike",
                detail=f"Motion energy {e:.3f} vs baseline {base:.3f} on {camera['name']} — check for scuffle.",
                frame=frame, meta={"energy": round(e, 4), "baseline": round(base, 4)})
