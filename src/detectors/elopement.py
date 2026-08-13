"""Detector 6: elopement/pacing prediction (memory care).

Tracks persons and counts approaches to exit-door zones: entering the zone,
leaving, re-entering = approach events. `approaches` within `window_seconds`
fires a WARNING — minutes before the door sensor would ever trip.
"""
from detectors.base import Detector, get_model, register


def in_zone(cx, cy, polygon):
    """Ray-casting point-in-polygon; polygon in normalized coords, cx/cy pixels."""
    if not polygon:
        return False
    # normalize point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


@register
class ElopementDetector(Detector):
    name = "elopement"

    def __init__(self, settings):
        super().__init__(settings)
        self.approaches_needed = int(self.settings.get("approaches", 3))
        self.window = float(self.settings.get("window_seconds", 300))
        self._model = None
        self._tracks = {}  # (camera, track_id) -> {"in_zone": bool, "approaches": [ts...]}

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get("exit_doors")
        if not zone:
            return
        if self._model is None:
            self._model = get_model("yolov8n.pt")
        res = self._model.track(frame, verbose=False, conf=0.45, persist=True,
                                classes=[0], tracker="bytetrack.yaml")[0]
        h, w = frame.shape[:2]
        for box in res.boxes or []:
            if box.id is None:
                continue
            track_id = int(box.id[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            key = (camera["id"], track_id)
            st = self._tracks.setdefault(key, {"in_zone": False, "approaches": []})
            now_in = in_zone(cx, cy, zone)
            if now_in and not st["in_zone"]:
                st["approaches"] = [t for t in st["approaches"] if ts - t <= self.window]
                st["approaches"].append(ts)
                if len(st["approaches"]) >= self.approaches_needed:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=self.name,
                        title="Repeated exit-zone approaches",
                        detail=f"{len(st['approaches'])} approaches to exit zone within {self.window/60:.0f} min on {camera['name']}.",
                        frame=None if camera.get("privacy_mode") == "skeleton" else frame,
                        meta={"approaches": len(st["approaches"]), "window_seconds": self.window},
                    )
                    st["approaches"] = []
            st["in_zone"] = now_in
