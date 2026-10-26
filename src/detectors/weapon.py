"""Detector 3: possible visible-weapon review signal.

Requires domain weights (detector_settings.weapon.weights). With COCO
fallback the knife class still fires; firearm classes need the custom
model. The detector emits an alert only; response actions remain governed by
the site's reviewed procedures and separate control systems.
"""
from detectors.base import Detector, get_model, register, run_inference
from model_paths import model_path

COCO_WEAPON_CLASSES = {34: "knife"}  # COCO ids that count as weapons in fallback
CUSTOM_WEAPON_CLASSES = {"pistol", "rifle", "firearm", "knife", "gun"}


@register
class WeaponDetector(Detector):
    name = "weapon"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("weights", model_path("weapon.pt"))
        self.conf = float(self.settings.get("confidence", 0.60))
        self._model = None

    def process(self, camera, frame, ts, ctx):
        if self._model is None:
            import os
            self._model = get_model(self.weights if os.path.exists(self.weights) else "yolov8n.pt")
        res = run_inference(self._model, frame, conf=self.conf)
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
                detail=f"Model labeled a possible {cls_name or 'knife'} at {conf:.0%} on {camera['name']}; verify immediately under site procedure.",
                frame=frame,
                meta={"class": cls_name, "confidence": conf},
            )
            return  # one alert per frame is enough; dedup handles the rest
