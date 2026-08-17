"""Detector 5: person and road-vehicle proximity review.

Uses COCO person and road-vehicle detections. When their image-plane centers are
closer than a camera-calibrated pixel threshold, it logs a snapshot for human
review. This proxy does not identify forklifts or determine that a near miss
occurred.
"""
from detectors.base import Detector, register
from marketplace.contract import boxes_of

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@register
class NearMissDetector(Detector):
    name = "near_miss"

    def __init__(self, settings):
        super().__init__(settings)
        self.dist = float(self.settings.get("distance_pixels", 120))
        self.conf = 0.45

    def process(self, camera, frame, ts, ctx):
        detections = boxes_of(
            frame,
            classes=[0, *VEHICLE_CLASSES],
            conf=self.conf,
            tracking_scope=(camera["id"], self.name),
        )
        persons = [(box[1], box[2], box[7]) for box in detections if box[0] == 0]
        vehicles = [
            (box[1], box[2], box[7], VEHICLE_CLASSES[box[0]])
            for box in detections
            if box[0] in VEHICLE_CLASSES
        ]
        height, width = frame.shape[:2]
        for person_x, person_y, person_track in persons:
            for vehicle_x, vehicle_y, vehicle_track, vehicle_class in vehicles:
                distance = (
                    ((person_x - vehicle_x) * width) ** 2
                    + ((person_y - vehicle_y) * height) ** 2
                ) ** 0.5
                if distance >= self.dist:
                    continue
                ctx.alerts.fire(
                    site=ctx.site,
                    camera=camera,
                    detector=self.name,
                    title="Person and vehicle proximity signal",
                    detail=(
                        f"A person detection and {vehicle_class} detection were "
                        f"{distance:.0f}px apart on {camera['name']}; review the frame."
                    ),
                    frame=frame,
                    meta={
                        "distance_px": distance,
                        "person_track": person_track,
                        "vehicle_track": vehicle_track,
                        "vehicle_class": vehicle_class,
                    },
                )
                return
