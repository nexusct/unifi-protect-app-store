"""Detector 2: bed-exit prediction (fall-risk residents, skeleton-only).

Watches the bed zone for the lying → sitting → edge sequence. Fires BEFORE
feet-on-floor: that's the prevention window. Keypoints only; no frames are
stored for privacy_mode: skeleton cameras (the alert carries angles/times,
not imagery).
"""
from detectors.base import Detector, get_model, register


@register
class BedExitDetector(Detector):
    name = "bed_exit"

    def __init__(self, settings):
        super().__init__(settings)
        self.conf = 0.5
        self.window = float(self.settings.get("window_seconds", 20))
        self._state = {}  # camera_id -> {"stage": str, "ts": float}
        self._model = None

    def _classify(self, kps, frame_h: int, bed_zone) -> str | None:
        """Classify posture: lying / sitting / edge (legs over bed edge, torso up)."""
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

            if torso_vertical < 0.08:  # shoulders ≈ hips height → lying
                return "lying"
            if torso_vertical > 0.15:  # torso upright
                if knees_visible and ankle_y and ankle_y > hip_y:
                    return "edge"  # upright torso, legs dropped past hips
                return "sitting"
            return None
        except Exception:
            return None

    def process(self, camera, frame, ts, ctx):
        if self._model is None:
            self._model = get_model("yolov8n-pose.pt")
        res = self._model(frame, verbose=False, conf=self.conf)[0]
        if res.keypoints is None or not len(res.keypoints.xy):
            return

        h = frame.shape[0]
        bed_zone = (camera.get("zones") or {}).get("bed")
        stage = None
        for kps in res.keypoints.data.cpu().numpy():
            stage = self._classify(kps, h, bed_zone)
            if stage:
                break
        if not stage:
            return

        st = self._state.get(camera["id"])
        seq = {"lying": 0, "sitting": 1, "edge": 2}
        if st and seq[stage] == seq[st["stage"]] + 1 and ts - st["ts"] <= self.window:
            st["stage"] = stage
            st["ts"] = ts
            if stage == "edge":
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=self.name,
                    title="Bed-exit sequence detected",
                    detail=f"lying→sitting→edge within {ts - st['start']:.0f}s on {camera['name']} — intervene before feet on floor.",
                    frame=None,  # never snapshot resident-room footage
                    meta={"window_seconds": ts - st["start"]},
                )
                self._state.pop(camera["id"], None)
        else:
            self._state[camera["id"]] = {"stage": stage, "ts": ts, "start": st["start"] if st and seq[stage] > seq.get(st["stage"], -1) else ts}
