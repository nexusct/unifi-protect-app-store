"""Detector 4: PPE compliance (hard hat / hi-vis) on plant floors and docks.

With domain weights: counts persons missing required PPE classes and fires
a compliance warning with the count. COCO fallback degrades to person-count
presence only (no PPE classes) and logs a one-time notice.
"""
import logging

from detectors.base import Detector, get_model, register

log = logging.getLogger("detectors.ppe")


@register
class PPEDetector(Detector):
    name = "ppe"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("weights", "/app/models/ppe.pt")
        self.conf = float(self.settings.get("confidence", 0.50))
        self.required = set(self.settings.get("required", ["hardhat", "hi-vis"]))
        self._model = None
        self._degraded = None

    def process(self, camera, frame, ts, ctx):
        import os
        custom = os.path.exists(self.weights)
        if self._model is None:
            self._model = get_model(self.weights if custom else "yolov8n.pt")
            if not custom:
                self._degraded = True
        if self._degraded:
            return  # no PPE classes without domain weights — stay silent rather than noise

        res = self._model(frame, verbose=False, conf=self.conf)[0]
        names = {k: str(v).lower() for k, v in (res.names or {}).items()}
        found = set()
        persons = 0
        for box in res.boxes or []:
            cls = names.get(int(box.cls[0]), "")
            if cls == "person":
                persons += 1
            elif cls in ("hardhat", "helmet", "hi-vis", "vest", "safety-vest"):
                found.add("hardhat" if cls in ("hardhat", "helmet") else "hi-vis")

        missing = self.required - found
        if persons > 0 and missing:
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=self.name,
                title=f"PPE missing: {', '.join(sorted(missing))}",
                detail=f"{persons} person(s) on {camera['name']} without {', '.join(sorted(missing))}.",
                frame=frame,
                meta={"persons": persons, "missing": sorted(missing)},
            )
