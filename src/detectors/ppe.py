"""Detector 4: PPE-item visibility review on plant floors and docks.

With domain weights, associates detected PPE item centers with each detected
person box and flags required items that were not observed for that person.
It does not determine wear quality or regulatory compliance. COCO fallback
stays silent because it lacks PPE classes.
"""
import logging
import os

from detectors.base import Detector, get_model, register, run_inference
from model_paths import model_path

log = logging.getLogger("detectors.ppe")


@register
class PPEDetector(Detector):
    name = "ppe"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("weights", model_path("ppe.pt"))
        self.conf = float(self.settings.get("confidence", 0.50))
        self.required = set(self.settings.get("required", ["hardhat", "hi-vis"]))
        self._model = None
        self._degraded = None

    @staticmethod
    def _missing_by_person(people, items, required):
        missing = {}
        for person_id, (x1, y1, x2, y2) in people:
            observed = {
                item
                for item, (cx, cy) in items
                if x1 <= cx <= x2 and y1 <= cy <= y2
            }
            absent = set(required) - observed
            if absent:
                missing[person_id] = absent
        return missing

    def process(self, camera, frame, ts, ctx):
        custom = os.path.exists(self.weights)
        if self._model is None:
            self._model = get_model(self.weights if custom else "yolov8n.pt")
            self._degraded = not custom
        if self._degraded:
            return

        result = run_inference(self._model, frame, conf=self.conf)
        names = {key: str(value).lower() for key, value in (result.names or {}).items()}
        h, w = frame.shape[:2]
        people = []
        items = []
        boxes = getattr(result, "boxes", None)
        for index, box in enumerate(boxes if boxes is not None else []):
            label = names.get(int(box.cls[0]), "")
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            normalized = (x1 / w, y1 / h, x2 / w, y2 / h)
            if label == "person":
                people.append((index, normalized))
                continue
            if label in ("hardhat", "helmet", "hi-vis", "vest", "safety-vest"):
                item = "hardhat" if label in ("hardhat", "helmet") else "hi-vis"
                items.append((item, ((normalized[0] + normalized[2]) / 2,
                                     (normalized[1] + normalized[3]) / 2)))

        missing = self._missing_by_person(people, items, self.required)
        if not missing:
            return
        summary = {
            str(person_id): sorted(values)
            for person_id, values in missing.items()
        }
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=self.name,
            title="PPE item visibility review",
            detail=(
                f"Required PPE item classes were not observed inside {len(missing)} "
                f"of {len(people)} person boxes on {camera['name']}; verify visually."
            ),
            frame=frame,
            meta={"person_boxes": len(people), "missing_by_detection": summary},
        )
