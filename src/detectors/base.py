"""Detector plugin interface and shared, serialized model registry."""
import logging
import os
import threading

log = logging.getLogger("detectors")

DEVICE = os.environ.get("VISION_DEVICE", "cuda")

_models = {}
_models_lock = threading.RLock()
_inference_lock = threading.RLock()

DETECTOR_REGISTRY = {}


def register(cls):
    DETECTOR_REGISTRY[cls.name] = cls
    return cls


def get_model(weights: str, kind: str = "detect", device: str | None = None):
    """Return one immutable-weight model per weights/device pair."""
    selected_device = device or os.environ.get("VISION_DEVICE", DEVICE)
    key = (weights, selected_device)
    with _models_lock:
        if key in _models:
            return _models[key]
        from ultralytics import YOLO

        log.info("loading model %s on %s", weights, selected_device)
        loaded = YOLO(weights)
        loaded.to(selected_device)
        _models[key] = loaded
        return loaded


def run_inference(model, frame, **kwargs):
    """Run stateless inference under one lock across camera threads/models."""
    options = {"verbose": False, **kwargs}
    with _inference_lock:
        return model.predict(frame, **options)[0]


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
