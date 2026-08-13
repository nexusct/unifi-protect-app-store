"""Detector plugin interface + shared model registry."""
import logging
import os

log = logging.getLogger("detectors")

DEVICE = os.environ.get("VISION_DEVICE", "cuda")

_models = {}

DETECTOR_REGISTRY = {}


def register(cls):
    DETECTOR_REGISTRY[cls.name] = cls
    return cls


def get_model(weights: str, kind: str = "detect"):
    """Shared ultralytics model cache — one GPU model per weights path."""
    if weights in _models:
        return _models[weights]
    from ultralytics import YOLO
    log.info("loading model %s on %s", weights, DEVICE)
    model = YOLO(weights)
    model.to(DEVICE)
    _models[weights] = model
    return model


class Detector:
    """Base class. Subclasses implement process(camera, frame, ts, ctx).

    ctx provides: alerts (AlertEngine), settings (per-detector config),
    access_events (recent door events buffer), site name.
    """
    name = "base"

    def __init__(self, settings: dict):
        self.settings = settings or {}

    def process(self, camera: dict, frame, ts: float, ctx):  # pragma: no cover
        raise NotImplementedError

    def status(self):
        return {"detector": self.name, "enabled": True}
