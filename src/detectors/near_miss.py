"""Detector 5: forklift–pedestrian near-miss logging (OSHA near-miss data).

ByteTrack tracks persons + vehicles; when centers approach within
distance_pixels, a near-miss is logged with a snapshot. Calibrate the
distance proxy per camera (pixels ≈ 1.5 m at typical dock angles).
"""
from detectors.base import Detector, get_model, register

VEHICLE_NAMES = {"car", "truck", "bus", "forklift", "motorcycle"}


@register
class NearMissDetector(Detector):
    name = "near_miss"

    def __init__(self, settings):
        super().__init__(settings)
        self.dist = float(self.settings.get("distance_pixels", 120))
        self.conf = 0.45
        self._model = None

    def process(self, camera, frame, ts, ctx):
        if self._model is None:
            self._model = get_model("yolov8n.pt")
        res = self._model.track(frame, verbose=False, conf=self.conf, persist=True,
                                tracker="bytetrack.yaml")[0]
        names = {k: str(v).lower() for k, v in (res.names or {}).items()}
        persons, vehicles = [], []
        for box in res.boxes or []:
            cls = names.get(int(box.cls[0]), "")
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if cls == "person":
                persons.append((cx, cy))
            elif cls in VEHICLE_NAMES:
                vehicles.append((cx, cy, cls))

        for (px, py) in persons:
            for (vx, vy, vcls) in vehicles:
                d = ((px - vx) ** 2 + (py - vy) ** 2) ** 0.5
                if d < self.dist:
                    ctx.alerts.fire(
                        site=ctx.site, camera=camera, detector=self.name,
                        title="Near-miss: person ↔ vehicle",
                        detail=f"Person within {d:.0f}px of {vcls} on {camera['name']}.",
                        frame=frame,
                        meta={"distance_px": d, "vehicle": vcls},
                    )
                    return
