"""Detector 3: visible-weapon detection → lockdown trigger.

Requires domain weights (detector_settings.weapon.weights). With COCO
fallback the knife class still fires; firearm classes need the custom
model. CRITICAL severity — payload includes lock=True so the Base44 ingest
function can trigger Access lockdown workflows.
"""
from detectors.base import Detector, get_model, register

COCO_WEAPON_CLASSES = {34: "knife"}  # COCO ids that count as weapons in fallback
CUSTOM_WEAPON_CLASSES = {"pistol", "rifle", "firearm", "knife", "gun"}


@register
class WeaponDetector(Detector):
    name = "weapon"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("weights", "/app/models/weapon.pt")
        self.conf = float(self.settings.get("confidence", 0.60))
        self._model = None

    def process(self, camera, frame, ts, ctx):
        if self._model is None:
            import os
            self._model = get_model(self.weights if os.path.exists(self.weights) else "yolov8n.pt")
        res = self._model(frame, verbose=False, conf=self.conf)[0]
        names = res.names or {}
        for box in res.boxes or []:
            cls_id = int(box.cls[0])
            cls_name = str(names.get(cls_id, "")).lower()
            is_weapon = cls_name in CUSTOM_WEAPON_CLASSES or cls_id in COCO_WEAPON_CLASSES
            if not is_weapon:
                continue
            conf = float(box.conf[0])
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=self.name,
                title=f"Possible weapon visible ({cls_name or 'knife'})",
                detail=f"{cls_name or 'knife'} detected at {conf:.0%} on {camera['name']}. Lockdown flag set.",
                frame=frame,
                meta={"class": cls_name, "confidence": conf, "lock": True},
            )
            return  # one alert per frame is enough; dedup handles the rest
