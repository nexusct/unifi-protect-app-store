"""Detector 7: GPU ALPR — plate detection (YOLO weights) + OCR (EasyOCR).

Works on ANY Protect camera — no per-camera AI hardware. Plates are logged
as info alerts with camera + timestamp; the Base44 side matches them against
expected-vendor lists for the arrival ledger.
"""
import logging
import re

from detectors.base import Detector, get_model, register

log = logging.getLogger("detectors.alpr")
PLATE_RE = re.compile(r"[A-Z0-9]{5,8}")


@register
class ALPRDetector(Detector):
    name = "alpr"

    def __init__(self, settings):
        super().__init__(settings)
        self.weights = self.settings.get("plate_weights", "/app/models/plate.pt")
        self.conf = float(self.settings.get("min_confidence", 0.45))
        self._model = None
        self._reader = None

    def process(self, camera, frame, ts, ctx):
        import os
        if not os.path.exists(self.weights):
            return  # no plate weights → silent (documented in README)
        if self._model is None:
            self._model = get_model(self.weights)
            import easyocr
            self._reader = easyocr.Reader(["en"], gpu=os.environ.get("VISION_DEVICE", "cuda") == "cuda")

        res = self._model(frame, verbose=False, conf=self.conf)[0]
        for box in res.boxes or []:
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            crop = frame[max(0, y1):y2, max(0, x1):x2]
            if crop.size == 0:
                continue
            texts = self._reader.readtext(crop, detail=0)
            plate = " ".join(texts).upper().replace(" ", "")
            m = PLATE_RE.search(plate)
            if not m:
                continue
            ctx.alerts.fire(
                site=ctx.site, camera=camera, detector=self.name,
                title=f"Plate read: {m.group(0)}",
                detail=f"{m.group(0)} at {camera['name']}.",
                frame=None,
                meta={"plate": m.group(0), "camera": camera["name"]},
            )
