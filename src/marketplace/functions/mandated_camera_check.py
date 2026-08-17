"""Camera view baseline check for a configured region."""
import numpy as np
from marketplace.contract import site_time, MarketplaceFunction

MANIFEST = {
    "id": "mandated-camera-check",
    "name": "Camera View Baseline Check",
    "tagline": "Flags a configured view region when edge structure drops below its learned baseline; camera movement, obstruction, and lighting changes can produce alerts.",
    "category": "Compliance",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "Polygon for the view region to compare with its learned baseline.",
        "edge_drop_ratio": "Fractional edge-structure drop that triggers review (default 0.5).",
        "check_hour": "UTC hour for the daily baseline comparison (default 6).",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.drop = float(self.settings.get("edge_drop_ratio", 0.5))
        self.check_hour = int(self.settings.get("check_hour", 6))
        self._baseline = {}
        self._samples = {}
        self._done_day = {}

    def process(self, camera, frame, ts, ctx):
        import time as _t
        import cv2
        zone = (camera.get("zones") or {}).get("mandated")
        if not zone:
            return
        tm = site_time(ts, ctx)
        if tm.tm_hour != self.check_hour:
            return
        day = _t.strftime("%Y-%m-%d", tm)
        key = camera["id"]
        if self._done_day.get(key) == day:
            return
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        edges = float(np.count_nonzero(cv2.Canny(crop, 60, 160))) / crop.size
        self._done_day[key] = day
        self._samples.setdefault(key, []).append(edges)
        if key not in self._baseline:
            if len(self._samples[key]) >= 7:
                self._baseline[key] = float(np.mean(self._samples[key]))
            return
        base = self._baseline[key]
        if base > 0 and (base - edges) / base >= self.drop:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=MANIFEST["id"],
                title="Camera view baseline changed",
                detail=f"Edge structure dropped {(base - edges)/base:.0%} from the learned baseline on {camera['name']}.",
                frame=frame, meta={"drop": round((base - edges) / base, 3)})
