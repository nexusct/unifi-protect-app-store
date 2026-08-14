"""Tarmac FOD — foreign object debris on the ramp zone.

A new small static object on the ramp where none should be = FOD alert.
FBOs and charter operators live by FOD walks; this is the continuous
version between walks.
"""
import numpy as np
from marketplace.contract import MarketplaceFunction

MANIFEST = {
    "id": "tarmac-fod",
    "name": "Tarmac FOD Watch",
    "tagline": "Something's on the ramp that wasn't there this morning. Found before the prop did.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "zone": "polygon — ramp area",
        "new_object_seconds": "int — persistence to alert (default 120)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.persist = float(self.settings.get("new_object_seconds", 120))
        self._bg = {}
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("ramp")
        if not zone:
            return
        import cv2
        h, w = frame.shape[:2]
        xs = [p[0] for p in zone]; ys = [p[1] for p in zone]
        crop = cv2.cvtColor(frame[int(min(ys)*h):int(max(ys)*h), int(min(xs)*w):int(max(xs)*w)], cv2.COLOR_BGR2GRAY)
        if crop.size == 0:
            return
        key = camera["id"]
        bg = self._bg.get(key)
        if bg is None or bg.shape != crop.shape:
            self._bg[key] = crop.astype("float32")
            return
        diff = cv2.absdiff(crop, bg.astype("uint8"))
        changed = float(np.count_nonzero(cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)[1])) / diff.size
        if 0.0005 < changed < 0.02:  # small new thing — not an aircraft movement
            self._since.setdefault(key, ts)
            if ts - self._since[key] >= self.persist:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Possible FOD on ramp",
                    detail=f"Small persistent change on ramp zone for {ts - self._since[key]:.0f}s on {camera['name']}.",
                    frame=frame, meta={"changed_ratio": round(changed, 5)})
                self._since[key] = ts
        else:
            self._since.pop(key, None)
        self._bg[key] = 0.995 * self._bg[key] + 0.005 * crop  # very slow adaptation
