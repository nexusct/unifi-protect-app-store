"""Greenhouse Visual Health — canopy color/shift change detection.

Weekly frame comparison of crop canopy zones: yellowing or wilting shows
as a hue shift before it's obvious on a walkthrough. Early water/disease
signal for greenhouse and nursery operators.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "greenhouse-visual-health",
    "name": "Canopy Visual Health",
    "tagline": "The canopy yellowed 8% this week. The camera caught it before the walkthrough.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — canopy area",
        "hue_shift": "float — alert threshold (default 6.0)",
        "check_hour": "int — daily check (default 12)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.shift_limit = float(self.settings.get("hue_shift", 6.0))
        self.check_hour = int(self.settings.get("check_hour", 12))
        self._baseline = None
        self._last_day = None

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("canopy")
        if not zone:
            return
        import time as _t
        import cv2
        tm = _t.gmtime(ts)
        if tm.tm_hour != self.check_hour:
            return
        day = _t.strftime("%Y-%m-%d", tm)
        if self._last_day == day:
            return
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)]
        if crop.size == 0:
            return
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mean_hue = float(np.mean(hsv[:, :, 0]))
        self._last_day = day
        if self._baseline is None:
            self._baseline = mean_hue
            return
        shift = abs(mean_hue - self._baseline)
        if shift >= self.shift_limit:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Canopy hue shift detected",
                detail=f"Mean hue shifted {shift:.1f} from baseline on {camera['name']} — check water/disease.",
                frame=frame, meta={"shift": round(shift, 2)})
            self._baseline = mean_hue  # accept the new state as baseline after alerting
