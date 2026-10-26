"""Raised-arm and high-motion pose signal.

Flags both wrists above the shoulders with high keypoint displacement. The
signal does not establish aggression, intent, or whether an incident will occur.
"""
from marketplace.contract import MarketplaceFunction, poses_of

MANIFEST = {
    "id": "aggression-posture",
    "name": "Raised-Arm Motion Review",
    "tagline": "Flags a sustained raised-arm, high-motion pose signature for calibrated staff review; it does not predict violence.",
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
        self._prev_kps = {}
        self._since = {}

    def _process_signals(self, camera, frame, ts, ctx, signals):
        camera_id = camera["id"]
        seen = set()
        for track_id, flagged in signals:
            key = (camera_id, track_id)
            seen.add(key)
            if not flagged:
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
                title="Raised-arm high-motion signature observed",
                detail=(
                    f"One tracked raised-arm pose showed high keypoint displacement "
                    f"for {held:.1f}s on {camera['name']}; review the frame."
                ),
                frame=frame,
                meta={"track": track_id, "sustain_s": held},
            )
            if delivered:
                self._since[key] = ts
        for key in list(self._since):
            if key[0] == camera_id and key not in seen:
                self._since.pop(key, None)

    def process(self, camera, frame, ts, ctx):
        import numpy as np

        camera_id = camera["id"]
        signals = []
        seen = set()
        for track_id, _cx, _cy, _x1, _y1, _x2, _y2, kps in poses_of(
            frame,
            conf=self.conf,
            tracking_scope=(camera_id, MANIFEST["id"]),
        ):
            key = (camera_id, track_id)
            seen.add(key)
            lw, rw, ls, rs = kps[9], kps[10], kps[5], kps[6]
            valid = min(lw[2], rw[2], ls[2], rs[2]) >= 0.3
            arms_up = valid and lw[1] < ls[1] and rw[1] < rs[1]
            previous = self._prev_kps.get(key)
            velocity = 0.0
            if previous is not None:
                velocity = float(np.mean(np.abs(kps[:, :2] - previous[:, :2])))
            self._prev_kps[key] = kps
            signals.append((track_id, bool(arms_up and velocity > 12)))

        for key in list(self._prev_kps):
            if key[0] == camera_id and key not in seen:
                self._prev_kps.pop(key, None)
        self._process_signals(camera, frame, ts, ctx, signals)
