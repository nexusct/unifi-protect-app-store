"""Banquet Setup Verification — room configured on schedule.

Compares the event-room zone to a set-up reference: table/chair edge
density reaches the configured signature before the event start, or
catering gets a "room not set" alert. Hotel banquet ops run on this.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "banquet-setup-verify",
    "name": "Banquet Setup Verification",
    "tagline": "6pm wedding, 4:30pm room not set. The alert went out at 4:31.",
    "category": "Intelligence",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — event room",
        "verify_hour": "int — hour to check setup (default 15)",
        "min_density_ratio": "float — vs set-up baseline (default 0.7)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.verify_hour = int(self.settings.get("verify_hour", 15))
        self.min_ratio = float(self.settings.get("min_density_ratio", 0.7))
        self._baseline = None
        self._samples = []
        self._done_day = None

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("event_room")
        if not zone:
            return
        import time as _t
        import cv2
        tm = _t.gmtime(ts)
        day = _t.strftime("%Y-%m-%d", tm)
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        density = float(np.count_nonzero(cv2.Canny(crop, 60, 160))) / crop.size
        # learn a "set" baseline from the busiest hour (assume peak = set)
        if tm.tm_hour == 12:
            self._samples.append(density)
            if len(self._samples) >= 20:
                self._baseline = float(np.mean(self._samples))
                self._samples = self._samples[-5:]
        if tm.tm_hour == self.verify_hour and self._done_day != day and self._baseline:
            self._done_day = day
            if density < self.baseline * self.min_ratio:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Event room not set on schedule",
                    detail=f"Setup density {density:.3f} vs expected {self._baseline * self.min_ratio:.3f} on {camera['name']}.",
                    frame=frame, meta={"density": round(density, 4)})
