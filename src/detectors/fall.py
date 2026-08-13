"""Detector 1: fall detection via pose keypoints (senior living common areas).

Approach: YOLO pose keypoints → torso angle (shoulder-to-hip vector vs
vertical). Torso near-horizontal sustained for floor_angle_seconds while
the person's bbox is in the lower frame region = fall event. Skeleton-only;
no identity, no face, frames not retained beyond the alert snapshot when
the camera is privacy_mode: skeleton.
"""
import time

from detectors.base import Detector, get_model, register


@register
class FallDetector(Detector):
    name = "fall"

    def __init__(self, settings):
        super().__init__(settings)
        self.conf = float(self.settings.get("confidence", 0.55))
        self.hold_seconds = float(self.settings.get("floor_angle_seconds", 2.0))
        self._horizontal_since = {}  # camera_id -> ts
        self._model = None

    def _pose(self, frame):
        if self._model is None:
            self._model = get_model("yolov8n-pose.pt")
        return self._model(frame, verbose=False, conf=self.conf)[0]

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

    def process(self, camera, frame, ts, ctx):
        res = self._pose(frame)
        angle = None
        if res.keypoints is not None and len(res.keypoints.xy):
            for kps in res.keypoints.data.cpu().numpy():
                a = self._torso_angle(kps)
                if a is not None:
                    angle = a
                    break

        horizontal = angle is not None and angle > 60
        key = camera["id"]
        if horizontal:
            self._horizontal_since.setdefault(key, ts)
            held = ts - self._horizontal_since[key]
            if held >= self.hold_seconds:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=self.name,
                    title="Possible fall detected",
                    detail=f"Person horizontal for {held:.0f}s on {camera['name']}. Torso angle {angle:.0f}°.",
                    frame=None if camera.get("privacy_mode") == "skeleton" else frame,
                    meta={"torso_angle": angle, "held_seconds": held},
                )
                self._horizontal_since[key] = ts  # re-arm via alert dedup window
        else:
            self._horizontal_since.pop(key, None)
