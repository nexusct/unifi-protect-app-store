"""Runtime composition for core detectors and marketplace functions."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def build_camera_detectors(cameras, settings, detector_classes):
    """Instantiate configured detectors; duplicate runtime IDs fail closed."""
    camera_ids = [camera["id"] for camera in cameras]
    seen = set()
    for camera_id in camera_ids:
        if camera_id in seen:
            raise ValueError(f"duplicate camera id {camera_id!r}")
        seen.add(camera_id)

    configured = {}
    for camera in cameras:
        instances = []
        for detector_name in camera.get("detectors", []):
            cls = detector_classes.get(detector_name)
            if not cls:
                camera_name = camera.get("name") or camera.get("id") or "unnamed camera"
                raise ValueError(f"unknown detector {detector_name!r} on {camera_name!r}")
            if getattr(cls, "api_function", False):
                # Declarative functions are compiled once by APIFunctionRuntime;
                # they are validated here but never duplicated per RTSP frame.
                continue
            detector_settings = dict(settings.get(detector_name, {}))
            detector_settings.update(camera.get(detector_name, {}))
            instances.append(cls(detector_settings))
        configured[camera["id"]] = instances
    return configured
