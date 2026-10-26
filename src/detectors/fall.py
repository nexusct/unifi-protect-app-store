"""Detector 1: possible-fall posture signal via pose keypoints.

Approach: YOLO pose keypoints → torso angle (shoulder-to-hip vector vs
vertical). A near-horizontal torso sustained for the configured duration is a
human-review signal, not a fall determination. No identity or face analysis is
performed. Skeleton-mode cameras do not retain alert snapshots.
"""
from detectors.base import Detector, register
from marketplace.contract import poses_of


@register
class FallDetector(Detector):
    name = "fall"

    def __init__(self, settings):
        super().__init__(settings)
        self.conf = float(self.settings.get("confidence", 0.55))
        self.hold_seconds = float(self.settings.get("floor_angle_seconds", 2.0))
        self._horizontal_since = {}  # (camera_id, track_id) -> ts

    @staticmethod
    def _torso_angle(kps) -> float | None:
        """Degrees from vertical for the shoulder-hip vector. 0=upright, 90=flat."""
        try:
            import math

            ls, rs, lh, rh = kps[5], kps[6], kps[11], kps[12]
            if min(ls[2], rs[2], lh[2], rh[2]) < 0.3:
                return None
            sx, sy = (ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2
            hx, hy = (lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2
            dx, dy = abs(sx - hx), abs(sy - hy)
            if dx + dy < 1e-3:
                return None
            return math.degrees(math.atan2(dx, dy))
        except Exception:
            return None

    def _process_angles(self, camera, frame, ts, ctx, angles):
        camera_id = camera["id"]
        seen = set()
        for track_id, angle in angles:
            key = (camera_id, track_id)
            seen.add(key)
            if angle is None or angle <= 60:
                self._horizontal_since.pop(key, None)
                continue
            self._horizontal_since.setdefault(key, ts)
            held = ts - self._horizontal_since[key]
            if held < self.hold_seconds:
                continue
            delivered = ctx.alerts.fire(
                site=ctx.site,
                camera=camera,
                detector=self.name,
                title="Possible fall posture signal",
                detail=(
                    f"Tracked person posture remained near-horizontal for {held:.0f}s "
                    f"on {camera['name']} (torso angle {angle:.0f}°); review promptly."
                ),
                frame=None if camera.get("privacy_mode") == "skeleton" else frame,
                meta={"track": track_id, "torso_angle": angle, "held_seconds": held},
            )
            if delivered:
                self._horizontal_since[key] = ts

        for key in list(self._horizontal_since):
            if key[0] == camera_id and key not in seen:
                self._horizontal_since.pop(key, None)

    def process(self, camera, frame, ts, ctx):
        angles = []
        for track_id, _cx, _cy, _x1, _y1, _x2, _y2, keypoints in poses_of(
            frame,
            conf=self.conf,
            tracking_scope=(camera["id"], self.name),
        ):
            angle = self._torso_angle(keypoints)
            if angle is not None:
                angles.append((track_id, angle))
        self._process_angles(camera, frame, ts, ctx, angles)
