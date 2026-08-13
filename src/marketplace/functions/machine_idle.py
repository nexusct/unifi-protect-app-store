"""Machine Idle Watch — visual OEE from activity energy.

Measures motion energy inside each machine's region. Active machine =
constant motion; idle = flat. Emits per-shift utilization percentages —
the OEE input plants normally buy sensors for.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "machine-idle",
    "name": "Machine Idle Watch",
    "tagline": "Which machines actually ran this shift — from video, not sensors.",
    "category": "Manufacturing & Warehouse",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "machines": "map of machine-name → polygon",
        "motion_threshold": "float — active energy level (default 0.02)",
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
                    title=f"{name}: {pct:.0f}% active this period",
                    detail=f"Machine {name} on {camera['name']} utilization {pct:.0f}%.",
                    frame=None, meta={"machine": name, "utilization_pct": round(pct, 1)})
