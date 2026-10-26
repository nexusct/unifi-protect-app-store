"""Detector 6: repeated exit-zone approach pattern (memory care).

Tracks person detections and counts approaches to configured exit-door zones.
The observable pattern does not infer intent or predict an elopement.
"""
import os

from detectors.base import Detector, register
from marketplace.contract import boxes_of, in_zone


@register
class ElopementDetector(Detector):
    name = "elopement"

    def __init__(self, settings):
        super().__init__(settings)
        self.approaches_needed = int(self.settings.get("approaches", 3))
        self.window = float(self.settings.get("window_seconds", 300))
        interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1"))
        self.max_gap = float(self.settings.get("max_track_gap_seconds", max(3.0, interval * 3.0)))
        self._tracks = {}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("exit_doors")
        if not zone:
            return

        camera_id = camera["id"]
        seen = set()
        for _cls, cx, cy, _x1, _y1, _x2, _y2, track_id in boxes_of(
            frame,
            classes=[0],
            conf=0.45,
            tracking_scope=(camera_id, self.name),
        ):
            key = (camera_id, track_id)
            seen.add(key)
            state = self._tracks.get(key)
            if state is None or ts - state.get("last_seen", ts) > self.max_gap:
                state = {"in_zone": False, "approaches": [], "last_seen": ts}
                self._tracks[key] = state
            now_in = in_zone(cx, cy, zone)
            if now_in and not state["in_zone"]:
                state["approaches"] = [
                    observed for observed in state["approaches"]
                    if ts - observed <= self.window
                ]
                state["approaches"].append(ts)
                if len(state["approaches"]) >= self.approaches_needed:
                    delivered = ctx.alerts.fire(
                        site=ctx.site,
                        camera=camera,
                        detector=self.name,
                        title="Repeated exit-zone approaches",
                        detail=(
                            f"One tracked person detection entered the exit zone "
                            f"{len(state['approaches'])} times within {self.window / 60:.0f} "
                            f"minutes on {camera['name']}; review required."
                        ),
                        frame=None if camera.get("privacy_mode") == "skeleton" else frame,
                        meta={
                            "track": track_id,
                            "approaches": len(state["approaches"]),
                            "window_seconds": self.window,
                        },
                    )
                    if delivered:
                        state["approaches"] = []
            state["in_zone"] = now_in
            state["last_seen"] = ts

        for key, state in list(self._tracks.items()):
            if key[0] == camera_id and key not in seen and ts - state["last_seen"] > self.max_gap:
                self._tracks.pop(key, None)
