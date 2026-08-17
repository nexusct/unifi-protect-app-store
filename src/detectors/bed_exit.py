"""Detector 2: bed-edge movement sequence review (skeleton-only).

Watches a configured bed zone for a per-track lying → sitting → edge posture
sequence. This is an observable movement signal, not a prediction or a
substitute for clinical monitoring. Alerts contain timing metadata, not imagery.
"""
import os

from detectors.base import Detector, register
from marketplace.contract import in_zone, poses_of


@register
class BedExitDetector(Detector):
    name = "bed_exit"

    def __init__(self, settings):
        super().__init__(settings)
        self.conf = 0.5
        self.window = float(self.settings.get("window_seconds", 20))
        interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1"))
        self.max_gap = float(self.settings.get("max_track_gap_seconds", max(3.0, interval * 3.0)))
        self._state = {}  # (camera_id, track_id) -> stage/timestamps

    @staticmethod
    def _classify(kps, frame_h: int) -> str | None:
        """Classify observable posture geometry as lying, sitting, or edge."""
        try:
            ls, rs, lh, rh = kps[5], kps[6], kps[11], kps[12]
            lk, rk, la, ra = kps[13], kps[14], kps[15], kps[16]
            if min(ls[2], rs[2], lh[2], rh[2]) < 0.3:
                return None
            shoulder_y = (ls[1] + rs[1]) / 2
            hip_y = (lh[1] + rh[1]) / 2
            torso_vertical = abs(hip_y - shoulder_y) / frame_h
            knees_visible = min(lk[2], rk[2]) > 0.3
            ankle_y = (la[1] + ra[1]) / 2 if min(la[2], ra[2]) > 0.3 else None
            if torso_vertical < 0.08:
                return "lying"
            if torso_vertical > 0.15:
                if knees_visible and ankle_y is not None and ankle_y > hip_y:
                    return "edge"
                return "sitting"
            return None
        except Exception:
            return None

    def _advance(self, camera, track_id, stage, ts, ctx):
        key = (camera["id"], track_id)
        state = self._state.get(key)
        if state and ts - state["last_seen"] > self.max_gap:
            state = None
            self._state.pop(key, None)

        if stage == "lying":
            if state is None or state["stage"] != "lying":
                self._state[key] = {
                    "stage": "lying",
                    "start": ts,
                    "stage_at": ts,
                    "last_seen": ts,
                }
            else:
                state["last_seen"] = ts
            return

        expected_previous = {"sitting": "lying", "edge": "sitting"}.get(stage)
        if state is None or state["stage"] != expected_previous:
            return
        if ts - state["stage_at"] > self.window or ts - state["start"] > self.window:
            self._state.pop(key, None)
            return

        if stage == "sitting":
            state.update({"stage": stage, "stage_at": ts, "last_seen": ts})
            return

        delivered = ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=self.name,
            title="Bed-edge movement sequence observed",
            detail=(
                f"One tracked pose followed a lying→sitting→edge sequence within "
                f"{ts - state['start']:.0f}s on {camera['name']}; review promptly."
            ),
            frame=None,
            meta={"track": track_id, "window_seconds": ts - state["start"]},
        )
        if delivered:
            self._state.pop(key, None)
        else:
            state["last_seen"] = ts

    def process(self, camera, frame, ts, ctx):
        bed_zone = (camera.get("zones") or {}).get("bed")
        if not bed_zone:
            return

        seen = set()
        for track_id, cx, cy, _x1, _y1, _x2, _y2, keypoints in poses_of(
            frame,
            conf=self.conf,
            tracking_scope=(camera["id"], self.name),
        ):
            if not in_zone(cx, cy, bed_zone):
                continue
            stage = self._classify(keypoints, frame.shape[0])
            if stage is None:
                continue
            seen.add((camera["id"], track_id))
            self._advance(camera, track_id, stage, ts, ctx)

        for key, state in list(self._state.items()):
            if key[0] == camera["id"] and key not in seen and ts - state["last_seen"] > self.max_gap:
                self._state.pop(key, None)
