"""Possible-fall posture review for public areas.

Uses a sustained horizontal torso-angle signal and saves an optional alert
snapshot for human review. It does not determine whether a fall occurred.
"""
import math

from marketplace.contract import MarketplaceFunction, poses_of

MANIFEST = {
    "id": "slip-fall",
    "name": "Possible Fall Review",
    "tagline": "Flags a sustained horizontal-pose signature and saves an alert snapshot for human review; calibrate per camera.",
    "category": "Property & Liability",
    "tier": "pro",
    "requires_gpu": True,
    "config_schema": {
        "confidence": "float (default 0.55)",
        "floor_angle_seconds": "float (default 1.5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.conf = float(self.settings.get("confidence", 0.55))
        self.hold = float(self.settings.get("floor_angle_seconds", 1.5))
        self._since = {}

    def process(self, camera, frame, ts, ctx):
        camera_id = camera["id"]
        seen = set()
        for track_id, _cx, _cy, _x1, _y1, _x2, _y2, kps in poses_of(
            frame,
            conf=self.conf,
            tracking_scope=(camera_id, MANIFEST["id"]),
        ):
            key = (camera_id, track_id)
            seen.add(key)
            ls, rs, lh, rh = kps[5], kps[6], kps[11], kps[12]
            if min(ls[2], rs[2], lh[2], rh[2]) < 0.3:
                self._since.pop(key, None)
                continue
            dx = abs((ls[0] + rs[0]) / 2 - (lh[0] + rh[0]) / 2)
            dy = abs((ls[1] + rs[1]) / 2 - (lh[1] + rh[1]) / 2)
            horizontal = dx + dy > 1e-3 and math.degrees(math.atan2(dx, dy)) > 60
            if not horizontal:
                self._since.pop(key, None)
                continue
            self._since.setdefault(key, ts)
            held = ts - self._since[key]
            if held < self.hold:
                continue
            delivered = ctx.alerts.fire(
                site=ctx.site,
                camera=camera,
                detector=MANIFEST["id"],
                title="Possible person-down posture",
                detail=(
                    f"One tracked horizontal-pose signature held {held:.1f}s on "
                    f"{camera['name']}; review the alert snapshot."
                ),
                frame=frame,
                meta={"track": track_id, "held": held},
            )
            if delivered:
                self._since[key] = ts

        for key in list(self._since):
            if key[0] == camera_id and key not in seen:
                self._since.pop(key, None)
