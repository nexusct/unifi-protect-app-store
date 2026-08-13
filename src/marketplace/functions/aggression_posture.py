"""Aggression Posture — raised-arms / erratic-motion escalation cue.

Pose keypoints: both wrists above shoulders + high keypoint velocity =
the pre-assault posture signature. Early-warning for ER waiting rooms,
classrooms, and front counters — seconds of notice before an incident.
"""
from collections import defaultdict
from marketplace.contract import MarketplaceFunction, model

MANIFEST = {
    "id": "aggression-posture",
    "name": "Aggression Early-Warning",
    "tagline": "Arms up, movements erratic — staff get seconds of warning.",
    "category": "People & Safety",
    "tier": "enterprise",
    "requires_gpu": True,
    "config_schema": {
        "confidence": "float (default 0.5)",
        "sustain_seconds": "float (default 2.5)",
    },
}


class Function(MarketplaceFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.conf = float(self.settings.get("confidence", 0.5))
        self.hold = float(self.settings.get("sustain_seconds", 2.5))
        self._model = None
        self._prev_kps = {}
        self._since = defaultdict(float)

    def process(self, camera, frame, ts, ctx):
        import os
        if self._model is None:
            self._model = model("yolov8n-pose.pt", os.environ.get("VISION_DEVICE", "cuda"))
        res = self._model(frame, verbose=False, conf=self.conf)[0]
        if res.keypoints is None or not len(res.keypoints.xy):
            return
        flagged = False
        for i, kps in enumerate(res.keypoints.data.cpu().numpy()):
            lw, rw, ls, rs = kps[9], kps[10], kps[5], kps[6]
            if min(lw[2], rw[2], ls[2], rs[2]) < 0.3:
                continue
            arms_up = lw[1] < ls[1] and rw[1] < rs[1]  # wrists above shoulders
            if not arms_up:
                continue
            prev = self._prev_kps.get(i)
            vel = 0.0
            if prev is not None:
                import numpy as np
                vel = float(np.mean(np.abs(kps[:, :2] - prev[:, :2])))
            self._prev_kps[i] = kps
            if vel > 12:  # px/frame erratic-motion proxy
                flagged = True
                break
        key = camera["id"]
        if flagged:
            if not self._since.get(key):
                self._since[key] = ts
            if ts - self._since[key] >= self.hold:
                ctx.alerts.fire(
                    site=ctx.site, camera=camera, detector=MANIFEST["id"],
                    title="Escalation posture detected",
                    detail=f"Raised-arms erratic-motion signature on {camera['name']} for {ts - self._since[key]:.1f}s.",
                    frame=frame, meta={"sustain_s": ts - self._since[key]})
                self._since[key] = 0
        else:
            self._since[key] = 0
