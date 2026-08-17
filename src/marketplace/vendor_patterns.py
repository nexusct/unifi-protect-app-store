"""Shared executable behaviors for independently implemented vendor-pattern plugins.

The marketplace modules in ``functions/`` keep literal customer contracts while
this module owns tracking, hold times, local baselines, custom-model fail-closed
behavior, redacted events, and bounded state. No vendor code, model, or output
format is used here.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import statistics
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from detectors import base as detector_base
from marketplace.contract import (
    CentroidTracker,
    MarketplaceFunction,
    boxes_of,
    crossed_line,
    in_zone,
    pixel_box,
    poses_of,
)

VEHICLE_CLASSES = {2, 3, 5, 7}
_PLATE_TEXT = re.compile(r"[A-Z0-9]{5,10}")


def _bounded_float(value, default, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(float(minimum), min(float(maximum), number))


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(int(minimum), min(int(maximum), number))


def _normalized_label(value):
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_-]+", "-", text).strip("-")[:80]


def _normalize_plate(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:16]


class VendorFunction(MarketplaceFunction):
    """Base with one redacted alert interface for all vendor-pattern modules."""

    function_id = "vendor-function"

    def _fire(self, camera, frame, ctx, title, detail, meta):
        return ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=self.function_id,
            title=title,
            detail=detail,
            frame=frame,
            meta=meta,
        )


class _AlertProxy:
    def __init__(self, target, function_id):
        self._target = target
        self._function_id = function_id

    def fire(self, **event):
        event["detector"] = self._function_id
        return self._target.fire(**event)

    def __getattr__(self, name):
        return getattr(self._target, name)


class DetectorAdapterFunction(VendorFunction):
    """Adapts a tested local detector while preserving the plugin event ID."""

    detector_cls = None
    detector_overrides = {}

    def __init__(self, settings):
        super().__init__(settings)
        merged = dict(settings or {})
        merged.update(self.detector_overrides)
        self._detector = self.detector_cls(merged)

    def process(self, camera, frame, ts, ctx):
        adapted = SimpleNamespace(**vars(ctx))
        adapted.alerts = _AlertProxy(ctx.alerts, self.function_id)
        return self._detector.process(camera, frame, ts, adapted)


class DomainObserver:
    """Fail-closed observer for customer-supplied, independently licensed weights."""

    def __init__(self, settings):
        self.weights = str((settings or {}).get("weights") or "")
        self.confidence = _bounded_float(
            (settings or {}).get("confidence"), 0.5, 0.05, 0.99
        )
        self._model = None
        self._tracker = CentroidTracker()

    def observe(self, frame, ts):
        if not self.weights or not Path(self.weights).is_file():
            return []
        if self._model is None:
            self._model = detector_base.get_model(self.weights)
        result = detector_base.run_inference(
            self._model, frame, conf=self.confidence
        )
        names = {
            int(key): _normalized_label(value)
            for key, value in (getattr(result, "names", None) or {}).items()
        }
        height, width = frame.shape[:2]
        raw = []
        boxes = getattr(result, "boxes", None)
        for box in boxes if boxes is not None else []:
            class_id = int(box.cls[0])
            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
            x1n = max(0.0, min(1.0, x1 / width))
            y1n = max(0.0, min(1.0, y1 / height))
            x2n = max(0.0, min(1.0, x2 / width))
            y2n = max(0.0, min(1.0, y2 / height))
            confidence = float(box.conf[0]) if hasattr(box, "conf") else 0.0
            raw.append(
                {
                    "class_id": class_id,
                    "label": names.get(class_id, f"class-{class_id}"),
                    "confidence": max(0.0, min(1.0, confidence)),
                    "cx": (x1n + x2n) / 2,
                    "cy": (y1n + y2n) / 2,
                    "x1": x1n,
                    "y1": y1n,
                    "x2": x2n,
                    "y2": y2n,
                }
            )
        track_ids = self._tracker.update(
            [(item["class_id"], item["cx"], item["cy"]) for item in raw], now=ts
        )
        for item, track_id in zip(raw, track_ids):
            item["track_id"] = track_id
        return raw


class PlateCandidateReader:
    def __init__(self, settings):
        settings = settings or {}
        self.weights = str(settings.get("weights") or "")
        self.confidence = _bounded_float(
            settings.get("min_confidence"), 0.65, 0.05, 0.99
        )
        self._model = None
        self._reader = None

    def observe(self, frame):
        if not self.weights or not Path(self.weights).is_file():
            return []
        if self._model is None:
            self._model = detector_base.get_model(self.weights)
            import easyocr

            self._reader = easyocr.Reader(
                ["en"], gpu=os.environ.get("VISION_DEVICE", "cuda") == "cuda"
            )
        result = detector_base.run_inference(
            self._model, frame, conf=self.confidence
        )
        candidates = []
        boxes = getattr(result, "boxes", None)
        for box in list(boxes if boxes is not None else [])[:8]:
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            if getattr(crop, "size", 0) == 0:
                continue
            text = _normalize_plate("".join(self._reader.readtext(crop, detail=0)))
            match = _PLATE_TEXT.search(text)
            if not match:
                continue
            candidates.append(
                {
                    "text": match.group(0),
                    "confidence": float(box.conf[0]) if hasattr(box, "conf") else 0.0,
                }
            )
        return candidates


class PlateWatchlistFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        values = settings.get("watchlist", []) if isinstance(settings, dict) else []
        if not isinstance(values, list):
            values = []
        self.watchlist = {
            normalized
            for normalized in (_normalize_plate(value) for value in values[:500])
            if _PLATE_TEXT.fullmatch(normalized)
        }
        self.min_confidence = _bounded_float(
            (settings or {}).get("min_confidence"), 0.8, 0.05, 0.99
        )
        self.cooldown = _bounded_float(
            (settings or {}).get("cooldown_seconds"), 300, 1, 86400
        )
        self._last = {}
        self._reader = PlateCandidateReader(settings or {})

    def process_candidates(self, camera, frame, ts, ctx, candidates):
        for candidate in list(candidates or [])[:16]:
            plate = _normalize_plate(candidate.get("text"))
            confidence = _bounded_float(candidate.get("confidence"), 0, 0, 1)
            if plate not in self.watchlist or confidence < self.min_confidence:
                continue
            digest = hashlib.sha256(plate.encode("ascii")).hexdigest()
            key = (camera["id"], digest)
            if ts - self._last.get(key, -math.inf) < self.cooldown:
                continue
            self._last[key] = ts
            self._fire(
                camera,
                None,
                ctx,
                f"Authorized plate-list candidate ending {plate[-3:]}",
                f"A locally configured plate-list candidate was observed on {camera['name']}; verify against source imagery and authorized records.",
                {
                    "plate_sha256": digest,
                    "plate_suffix": plate[-3:],
                    "confidence": round(confidence, 4),
                },
            )

    def process(self, camera, frame, ts, ctx):
        return self.process_candidates(
            camera, frame, ts, ctx, self._reader.observe(frame)
        )


class VehicleAttributeFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.cooldown = _bounded_float(
            (settings or {}).get("cooldown_seconds"), 60, 1, 86400
        )
        self._last = {}
        self._observer = DomainObserver(settings or {})

    def process_observations(self, camera, frame, ts, ctx, observations):
        for observation in list(observations or [])[:64]:
            label = _normalized_label(observation.get("label"))
            if not label or label in {"person", "plate"}:
                continue
            track_id = int(observation.get("track_id", -1))
            key = (camera["id"], track_id, label)
            if ts - self._last.get(key, -math.inf) < self.cooldown:
                continue
            self._last[key] = ts
            self._fire(
                camera,
                None,
                ctx,
                "Vehicle attribute candidate",
                f"The configured domain model returned '{label}' on {camera['name']}; verify visually before use.",
                {
                    "track": track_id,
                    "classification": label,
                    "confidence": round(
                        _bounded_float(observation.get("confidence"), 0, 0, 1), 4
                    ),
                },
            )

    def process(self, camera, frame, ts, ctx):
        return self.process_observations(
            camera, frame, ts, ctx, self._observer.observe(frame, ts)
        )


class VehicleZoneDwellFunction(VendorFunction):
    zone_key = "restricted_parking"

    def __init__(self, settings):
        super().__init__(settings)
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 120, 1, 86400
        )
        self._since = {}
        self._alerted = set()

    def process_observations(self, camera, frame, ts, ctx, detections, zone):
        inside = set()
        for item in detections or []:
            if int(item.get("class_id", -1)) not in VEHICLE_CLASSES:
                continue
            if not in_zone(float(item["cx"]), float(item["cy"]), zone):
                continue
            track = int(item["track_id"])
            key = (camera["id"], track)
            inside.add(key)
            self._since.setdefault(key, ts)
            dwell = ts - self._since[key]
            if dwell >= self.hold and key not in self._alerted:
                self._alerted.add(key)
                self._fire(
                    camera,
                    frame,
                    ctx,
                    "Sustained vehicle-zone presence",
                    f"A vehicle-class track remained in the configured parking-review zone on {camera['name']} for {dwell:.0f}s.",
                    {"vehicle_track": track, "dwell_seconds": round(dwell, 3)},
                )
        for key in list(self._since):
            if key[0] == camera["id"] and key not in inside:
                self._since.pop(key, None)
                self._alerted.discard(key)

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        observations = [
            {
                "class_id": box[0],
                "cx": box[1],
                "cy": box[2],
                "track_id": box[7],
            }
            for box in boxes_of(
                frame,
                classes=sorted(VEHICLE_CLASSES),
                tracking_scope=(camera["id"], self.function_id),
            )
        ]
        return self.process_observations(camera, frame, ts, ctx, observations, zone)


class StationaryVehicleFunction(VendorFunction):
    zone_key = "traffic_lane"

    def __init__(self, settings):
        super().__init__(settings)
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 20, 1, 3600
        )
        self.movement = _bounded_float(
            (settings or {}).get("movement_threshold"), 0.01, 0.001, 0.25
        )
        self._state = {}

    def process_positions(self, camera, frame, ts, ctx, positions):
        seen = set()
        for track, position in (positions or {}).items():
            track = int(track)
            key = (camera["id"], track)
            seen.add(key)
            point = (float(position[0]), float(position[1]))
            state = self._state.get(key)
            if state is None:
                self._state[key] = {
                    "point": point,
                    "stationary_since": ts,
                    "last_seen": ts,
                    "alerted": False,
                }
                continue
            distance = math.dist(state["point"], point)
            if distance > self.movement:
                state["stationary_since"] = ts
                state["alerted"] = False
            state["point"] = point
            state["last_seen"] = ts
            dwell = ts - state["stationary_since"]
            if dwell >= self.hold and not state["alerted"]:
                state["alerted"] = True
                self._fire(
                    camera,
                    frame,
                    ctx,
                    "Stopped-vehicle lane review",
                    f"A vehicle-class track showed less than the configured image-plane movement on {camera['name']} for {dwell:.0f}s.",
                    {"vehicle_track": track, "stationary_seconds": round(dwell, 3)},
                )
        for key in list(self._state):
            if key[0] == camera["id"] and key not in seen:
                self._state.pop(key, None)

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        positions = {
            int(box[7]): (box[1], box[2])
            for box in boxes_of(
                frame,
                classes=sorted(VEHICLE_CLASSES),
                tracking_scope=(camera["id"], self.function_id),
            )
            if in_zone(box[1], box[2], zone)
        }
        return self.process_positions(camera, frame, ts, ctx, positions)


class CountHoldFunction(VendorFunction):
    zone_key = "spillback"
    default_threshold = 5

    def __init__(self, settings):
        super().__init__(settings)
        self.threshold = _bounded_int(
            (settings or {}).get("vehicle_threshold"), self.default_threshold, 1, 1000
        )
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 30, 1, 3600
        )
        self._state = {}

    def process_count(self, camera, frame, ts, ctx, count):
        key = camera["id"]
        count = max(0, int(count))
        if count < self.threshold:
            self._state.pop(key, None)
            return
        state = self._state.setdefault(key, {"since": ts, "alerted": False})
        dwell = ts - state["since"]
        if dwell >= self.hold and not state["alerted"]:
            state["alerted"] = True
            self._fire(
                camera,
                frame,
                ctx,
                "Traffic queue spillback review",
                f"{count} vehicle-class detections remained in the configured spillback zone on {camera['name']} for {dwell:.0f}s.",
                {"vehicle_count": count, "hold_seconds": round(dwell, 3)},
            )

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        count = sum(
            1
            for box in boxes_of(frame, classes=sorted(VEHICLE_CLASSES))
            if in_zone(box[1], box[2], zone)
        )
        return self.process_count(camera, frame, ts, ctx, count)


class UnusualDwellBaselineFunction(VendorFunction):
    zone_key = "dwell_baseline"

    def __init__(self, settings):
        super().__init__(settings)
        self.min_samples = _bounded_int(
            (settings or {}).get("min_samples"), 20, 5, 200
        )
        self.minimum = _bounded_float(
            (settings or {}).get("minimum_seconds"), 60, 1, 86400
        )
        self.factor = _bounded_float(
            (settings or {}).get("anomaly_factor"), 3, 1.1, 20
        )
        self._baseline = defaultdict(lambda: deque(maxlen=200))
        self._active = {}
        self._alerted = set()

    def record_completed_dwell(self, camera_id, dwell):
        value = _bounded_float(dwell, 0, 0, 86400)
        if value > 0:
            self._baseline[str(camera_id)].append(value)

    def process_current_dwell(self, camera, frame, ts, ctx, track, dwell):
        samples = self._baseline[camera["id"]]
        if len(samples) < self.min_samples:
            return
        median = statistics.median(samples)
        threshold = max(self.minimum, median * self.factor)
        key = (camera["id"], int(track))
        if dwell >= threshold and key not in self._alerted:
            self._alerted.add(key)
            self._fire(
                camera,
                frame,
                ctx,
                "Unusual dwell review",
                f"A person track remained in the configured zone on {camera['name']} for {dwell:.0f}s, above its local completed-dwell baseline.",
                {
                    "track": int(track),
                    "dwell_seconds": round(float(dwell), 3),
                    "baseline_median_seconds": round(float(median), 3),
                    "baseline_samples": len(samples),
                },
            )

    def process_tracks(self, camera, frame, ts, ctx, positions, zone):
        current = set()
        for track, point in (positions or {}).items():
            key = (camera["id"], int(track))
            if not in_zone(float(point[0]), float(point[1]), zone):
                continue
            current.add(key)
            state = self._active.setdefault(key, {"since": ts})
            self.process_current_dwell(
                camera, frame, ts, ctx, track, ts - state["since"]
            )
        for key in list(self._active):
            if key[0] != camera["id"] or key in current:
                continue
            dwell = ts - self._active.pop(key)["since"]
            self.record_completed_dwell(camera["id"], dwell)
            self._alerted.discard(key)

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        positions = {
            int(box[7]): (box[1], box[2])
            for box in boxes_of(
                frame,
                classes=[0],
                tracking_scope=(camera["id"], self.function_id),
            )
        }
        return self.process_tracks(camera, frame, ts, ctx, positions, zone)


class QueueAbandonmentFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.minimum_wait = _bounded_float(
            (settings or {}).get("minimum_wait_seconds"), 60, 1, 7200
        )
        self.missing_grace = _bounded_float(
            (settings or {}).get("missing_grace_seconds"), 3, 0, 30
        )
        self._state = {}

    def _emit_if_abandoned(self, camera, frame, ts, ctx, key, state):
        dwell = state["last_seen"] - state["queue_since"]
        if dwell < self.minimum_wait or state["service_seen"]:
            return
        self._fire(
            camera,
            frame,
            ctx,
            "Queue abandonment review",
            f"A person track left the configured queue after {dwell:.0f}s without entering the configured service zone on {camera['name']}.",
            {"track": key[1], "queue_seconds": round(dwell, 3)},
        )

    def process_tracks(self, camera, frame, ts, ctx, positions, queue_zone, service_zone):
        seen = set()
        for track, point in (positions or {}).items():
            key = (camera["id"], int(track))
            seen.add(key)
            inside_queue = in_zone(float(point[0]), float(point[1]), queue_zone)
            inside_service = in_zone(float(point[0]), float(point[1]), service_zone)
            state = self._state.get(key)
            if inside_queue and state is None:
                state = {
                    "queue_since": ts,
                    "last_seen": ts,
                    "service_seen": False,
                    "in_queue": True,
                }
                self._state[key] = state
            if state is None:
                continue
            state["last_seen"] = ts
            state["service_seen"] = state["service_seen"] or inside_service
            if state["in_queue"] and not inside_queue:
                self._emit_if_abandoned(camera, frame, ts, ctx, key, state)
                self._state.pop(key, None)
            else:
                state["in_queue"] = inside_queue
        for key, state in list(self._state.items()):
            if key[0] != camera["id"] or key in seen:
                continue
            if ts - state["last_seen"] >= self.missing_grace:
                self._emit_if_abandoned(camera, frame, ts, ctx, key, state)
                self._state.pop(key, None)

    def process(self, camera, frame, ts, ctx):
        zones = camera.get("zones") or {}
        queue_zone = zones.get("queue")
        service_zone = zones.get("service")
        if not queue_zone or not service_zone:
            return
        positions = {
            int(box[7]): (box[1], box[2])
            for box in boxes_of(
                frame,
                classes=[0],
                tracking_scope=(camera["id"], self.function_id),
            )
        }
        return self.process_tracks(
            camera, frame, ts, ctx, positions, queue_zone, service_zone
        )


class ForkliftProximityFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.distance = _bounded_float(
            (settings or {}).get("distance_ratio"), 0.12, 0.01, 1
        )
        self.cooldown = _bounded_float(
            (settings or {}).get("cooldown_seconds"), 30, 1, 3600
        )
        self._last = {}
        self._observer = DomainObserver(settings or {})

    def process_detections(self, camera, frame, ts, ctx, observations):
        people = [item for item in observations or [] if item.get("label") == "person"]
        forklifts = [
            item for item in observations or [] if item.get("label") == "forklift"
        ]
        for person in people:
            for forklift in forklifts:
                distance = math.dist(
                    (float(person["cx"]), float(person["cy"])),
                    (float(forklift["cx"]), float(forklift["cy"])),
                )
                if distance > self.distance:
                    continue
                key = (
                    camera["id"],
                    int(person["track_id"]),
                    int(forklift["track_id"]),
                )
                if ts - self._last.get(key, -math.inf) < self.cooldown:
                    continue
                self._last[key] = ts
                self._fire(
                    camera,
                    frame,
                    ctx,
                    "Person and forklift proximity review",
                    f"Person and forklift model tracks were {distance:.3f} normalized image units apart on {camera['name']}; review the frame.",
                    {
                        "person_track": key[1],
                        "forklift_track": key[2],
                        "distance_ratio": round(distance, 4),
                    },
                )
                return

    def process(self, camera, frame, ts, ctx):
        return self.process_detections(
            camera, frame, ts, ctx, self._observer.observe(frame, ts)
        )


class PerimeterClimbFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 2, 0.5, 60
        )
        self.margin = _bounded_float(
            (settings or {}).get("boundary_margin"), 0.15, 0.01, 0.5
        )
        self._since = {}
        self._alerted = set()

    def process_signals(self, camera, frame, ts, ctx, signals):
        active = set()
        for signal in signals or []:
            track = int(signal["track_id"])
            key = (camera["id"], track)
            if not signal.get("near_boundary") or not signal.get("climb_pose"):
                continue
            active.add(key)
            self._since.setdefault(key, ts)
            dwell = ts - self._since[key]
            if dwell >= self.hold and key not in self._alerted:
                self._alerted.add(key)
                self._fire(
                    camera,
                    frame,
                    ctx,
                    "Perimeter climbing-pose review",
                    f"A sustained pose signal near the configured perimeter boundary was observed on {camera['name']}; verify visually.",
                    {"track": track, "hold_seconds": round(dwell, 3)},
                )
        for key in list(self._since):
            if key[0] == camera["id"] and key not in active:
                self._since.pop(key, None)
                self._alerted.discard(key)

    def process(self, camera, frame, ts, ctx):
        boundary = (camera.get("zones") or {}).get("perimeter_boundary")
        if not isinstance(boundary, list) or len(boundary) != 2:
            return
        boundary_y = (float(boundary[0][1]) + float(boundary[1][1])) / 2
        height = frame.shape[0]
        signals = []
        for track, _cx, cy, _x1, _y1, _x2, _y2, points in poses_of(
            frame, tracking_scope=(camera["id"], self.function_id)
        ):
            try:
                wrists = [float(points[index][1]) / height for index in (9, 10)]
                hips = [float(points[index][1]) / height for index in (11, 12)]
            except (IndexError, TypeError, ValueError):
                continue
            signals.append(
                {
                    "track_id": track,
                    "near_boundary": abs(float(cy) - boundary_y) <= self.margin,
                    "climb_pose": min(wrists) < boundary_y < max(hips),
                }
            )
        return self.process_signals(camera, frame, ts, ctx, signals)


class VehicleWrongWayFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        allowed = _bounded_int((settings or {}).get("allowed_direction"), 1, -1, 1)
        self.allowed = allowed if allowed in {-1, 1} else 1
        self._previous = {}
        self._last_alert = {}
        self.cooldown = _bounded_float(
            (settings or {}).get("cooldown_seconds"), 30, 1, 3600
        )

    def process_tracks(self, camera, frame, ts, ctx, tracks, line):
        current = set()
        for track, point in (tracks or {}).items():
            track = int(track)
            key = (camera["id"], track)
            current.add(key)
            now = (float(point[0]), float(point[1]))
            previous = self._previous.get(key)
            self._previous[key] = now
            if previous is None:
                continue
            direction = crossed_line(previous, now, line)
            if direction == 0 or direction == self.allowed:
                continue
            if ts - self._last_alert.get(key, -math.inf) < self.cooldown:
                continue
            self._last_alert[key] = ts
            self._fire(
                camera,
                frame,
                ctx,
                "Vehicle wrong-way crossing review",
                f"A vehicle-class track crossed the configured line opposite the allowed direction on {camera['name']}.",
                {"vehicle_track": track, "direction": direction},
            )
        for key in list(self._previous):
            if key[0] == camera["id"] and key not in current:
                self._previous.pop(key, None)

    def process(self, camera, frame, ts, ctx):
        line = (camera.get("zones") or {}).get("vehicle_direction_line")
        if not isinstance(line, list) or len(line) != 2:
            return
        tracks = {
            int(box[7]): (box[1], box[2])
            for box in boxes_of(
                frame,
                classes=sorted(VEHICLE_CLASSES),
                tracking_scope=(camera["id"], self.function_id),
            )
        }
        return self.process_tracks(camera, frame, ts, ctx, tracks, line)


class RollingCountAnomalyFunction(VendorFunction):
    zone_key = "occupancy"

    def __init__(self, settings):
        super().__init__(settings)
        self.min_samples = _bounded_int(
            (settings or {}).get("min_samples"), 20, 5, 200
        )
        self.factor = _bounded_float(
            (settings or {}).get("anomaly_factor"), 2, 1.1, 20
        )
        self._history = defaultdict(lambda: deque(maxlen=200))
        self._active = set()

    def process_count(self, camera, frame, ts, ctx, count):
        count = max(0, int(count))
        history = self._history[camera["id"]]
        if len(history) < self.min_samples:
            history.append(count)
            return
        baseline = float(statistics.median(history))
        high = count >= max(1.0, baseline * self.factor)
        low = baseline > 0 and count <= baseline / self.factor
        key = camera["id"]
        if (high or low) and key not in self._active:
            self._active.add(key)
            self._fire(
                camera,
                None,
                ctx,
                "Occupancy-flow anomaly review",
                f"The current anonymous person count ({count}) differs materially from the local rolling median ({baseline:.1f}) on {camera['name']}.",
                {
                    "current_count": count,
                    "baseline_median": round(baseline, 3),
                    "baseline_samples": len(history),
                    "direction": "high" if high else "low",
                },
            )
            return
        if not high and not low:
            self._active.discard(key)
            history.append(count)

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        count = sum(
            1
            for box in boxes_of(frame, classes=[0])
            if in_zone(box[1], box[2], zone)
        )
        return self.process_count(camera, frame, ts, ctx, count)


class MetricBaselineFunction(VendorFunction):
    metric_mode = "absolute"
    zone_key = None
    event_title = "Visual baseline change review"

    def __init__(self, settings):
        super().__init__(settings)
        self.min_samples = _bounded_int(
            (settings or {}).get("min_samples"), 20, 3, 200
        )
        self.threshold = _bounded_float(
            (settings or {}).get("change_threshold"), 0.2, 0.001, 1
        )
        self.factor = _bounded_float(
            (settings or {}).get("anomaly_factor"), 3, 1.1, 20
        )
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 5, 0, 3600
        )
        self._history = defaultdict(lambda: deque(maxlen=200))
        self._anomaly_since = {}
        self._alerted = set()

    def process_metric(self, camera, frame, ts, ctx, value):
        value = _bounded_float(value, 0, 0, 1)
        history = self._history[camera["id"]]
        if len(history) < self.min_samples:
            history.append(value)
            return
        baseline = float(statistics.median(history))
        if self.metric_mode == "ratio":
            anomalous = value >= max(0.001, baseline * self.factor)
        else:
            anomalous = abs(value - baseline) >= self.threshold
        key = camera["id"]
        if not anomalous:
            self._anomaly_since.pop(key, None)
            self._alerted.discard(key)
            history.append(value)
            return
        self._anomaly_since.setdefault(key, ts)
        dwell = ts - self._anomaly_since[key]
        if dwell < self.hold or key in self._alerted:
            return
        self._alerted.add(key)
        self._fire(
            camera,
            frame,
            ctx,
            self.event_title,
            f"A sustained local visual metric change was measured on {camera['name']}; inspect the scene to determine the cause.",
            {
                "metric": round(value, 5),
                "baseline_median": round(baseline, 5),
                "baseline_samples": len(history),
                "hold_seconds": round(dwell, 3),
            },
        )


class FloorAppearanceFunction(MetricBaselineFunction):
    zone_key = "floor_review"
    event_title = "Floor appearance change review"

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        xs = [float(point[0]) for point in zone]
        ys = [float(point[1]) for point in zone]
        left, top, right, bottom = pixel_box(
            frame, min(xs), min(ys), max(xs), max(ys)
        )
        crop = frame[top:bottom, left:right]
        if getattr(crop, "size", 0) == 0:
            return
        pixels = crop.astype(np.float32)
        blue_excess = (
            (pixels[..., 0] - pixels[..., 2] > 20)
            & (pixels[..., 0] - pixels[..., 1] > 10)
        )
        luminance = pixels.mean(axis=2)
        reflective = (luminance > 190) & (pixels.max(axis=2) - pixels.min(axis=2) < 25)
        metric = float(np.mean(blue_excess | reflective))
        return self.process_metric(camera, frame, ts, ctx, metric)


class MotionBaselineFunction(MetricBaselineFunction):
    metric_mode = "ratio"
    event_title = "Unusual motion-energy review"

    def __init__(self, settings):
        super().__init__(settings)
        self._previous_frame = {}

    def process(self, camera, frame, ts, ctx):
        gray = frame.astype(np.float32).mean(axis=2)[::4, ::4]
        previous = self._previous_frame.get(camera["id"])
        self._previous_frame[camera["id"]] = gray
        if previous is None or previous.shape != gray.shape:
            return
        metric = float(np.mean(np.abs(gray - previous)) / 255.0)
        return self.process_metric(camera, frame, ts, ctx, metric)


class ObjectRemovalFunction(VendorFunction):
    zone_key = "asset_zone"

    def __init__(self, settings):
        super().__init__(settings)
        self.baseline_samples = _bounded_int(
            (settings or {}).get("baseline_samples"), 10, 3, 200
        )
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 10, 0, 3600
        )
        self.minimum_present = _bounded_int(
            (settings or {}).get("minimum_present"), 1, 1, 1000
        )
        values = (settings or {}).get("class_ids", list(VEHICLE_CLASSES))
        if not isinstance(values, list):
            values = list(VEHICLE_CLASSES)
        self.class_ids = sorted(
            {int(value) for value in values[:32] if str(value).lstrip("-").isdigit()}
        ) or sorted(VEHICLE_CLASSES)
        self._history = defaultdict(lambda: deque(maxlen=200))
        self._missing_since = {}
        self._alerted = set()

    def process_count(self, camera, frame, ts, ctx, count):
        count = max(0, int(count))
        history = self._history[camera["id"]]
        if len(history) < self.baseline_samples:
            history.append(count)
            return
        baseline = float(statistics.median(history))
        key = camera["id"]
        missing = baseline >= self.minimum_present and count < self.minimum_present
        if not missing:
            self._missing_since.pop(key, None)
            self._alerted.discard(key)
            history.append(count)
            return
        self._missing_since.setdefault(key, ts)
        dwell = ts - self._missing_since[key]
        if dwell >= self.hold and key not in self._alerted:
            self._alerted.add(key)
            self._fire(
                camera,
                frame,
                ctx,
                "Configured object-removal review",
                f"The configured asset-zone count fell from a local median of {baseline:.1f} to {count} on {camera['name']}; verify the scene.",
                {
                    "baseline_median": round(baseline, 3),
                    "current_count": count,
                    "hold_seconds": round(dwell, 3),
                },
            )

    def process(self, camera, frame, ts, ctx):
        zone = (camera.get("zones") or {}).get(self.zone_key)
        if not zone:
            return
        count = sum(
            1
            for box in boxes_of(frame, classes=self.class_ids)
            if in_zone(box[1], box[2], zone)
        )
        return self.process_count(camera, frame, ts, ctx, count)


class AssemblySequenceFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        sequence = (settings or {}).get("expected_sequence", [])
        if not isinstance(sequence, list):
            sequence = []
        self.sequence = [
            label
            for label in (_normalized_label(value) for value in sequence[:32])
            if label
        ]
        self._index = defaultdict(int)
        self._last_stage = {}
        self._observer = DomainObserver(settings or {})

    def process_stage(self, camera, frame, ts, ctx, stage):
        stage = _normalized_label(stage)
        if not stage or not self.sequence:
            return
        if self._last_stage.get(camera["id"]) == stage:
            return
        self._last_stage[camera["id"]] = stage
        index = self._index[camera["id"]]
        expected = self.sequence[index]
        if stage == expected:
            index += 1
            self._index[camera["id"]] = 0 if index == len(self.sequence) else index
            return
        if stage not in self.sequence:
            return
        self._fire(
            camera,
            frame,
            ctx,
            "Assembly stage-order review",
            f"The configured domain model observed stage '{stage}' while '{expected}' was expected on {camera['name']}; verify the process.",
            {"expected_stage": expected, "observed_stage": stage, "step_index": index},
        )
        self._index[camera["id"]] = 1 if stage == self.sequence[0] else 0

    def process(self, camera, frame, ts, ctx):
        observations = self._observer.observe(frame, ts)
        candidates = [
            item for item in observations if item.get("label") in set(self.sequence)
        ]
        if not candidates:
            return
        stage = max(candidates, key=lambda item: item.get("confidence", 0))["label"]
        return self.process_stage(camera, frame, ts, ctx, stage)


class PackageLabelFunction(VendorFunction):
    def __init__(self, settings):
        super().__init__(settings)
        self.hold = _bounded_float(
            (settings or {}).get("hold_seconds"), 2, 0, 300
        )
        self._missing_since = {}
        self._alerted = set()
        self._observer = DomainObserver(settings or {})

    def process_observations(self, camera, frame, ts, ctx, packages, labels):
        missing = set()
        for package in packages or []:
            track = int(package["track_id"])
            key = (camera["id"], track)
            has_label = any(
                float(package["x1"]) <= float(label["cx"]) <= float(package["x2"])
                and float(package["y1"]) <= float(label["cy"]) <= float(package["y2"])
                for label in labels or []
            )
            if has_label:
                self._missing_since.pop(key, None)
                self._alerted.discard(key)
                continue
            missing.add(key)
            self._missing_since.setdefault(key, ts)
            dwell = ts - self._missing_since[key]
            if dwell >= self.hold and key not in self._alerted:
                self._alerted.add(key)
                self._fire(
                    camera,
                    frame,
                    ctx,
                    "Shipping-label presence review",
                    f"The configured domain model did not observe a label center inside a package box on {camera['name']} for {dwell:.0f}s; verify the package.",
                    {"package_track": track, "hold_seconds": round(dwell, 3)},
                )
        for key in list(self._missing_since):
            if key[0] == camera["id"] and key not in missing:
                self._missing_since.pop(key, None)
                self._alerted.discard(key)

    def process(self, camera, frame, ts, ctx):
        observations = self._observer.observe(frame, ts)
        packages = [
            item
            for item in observations
            if item.get("label") in {"package", "parcel", "box"}
        ]
        labels = [
            item
            for item in observations
            if item.get("label") in {"label", "shipping-label"}
        ]
        return self.process_observations(camera, frame, ts, ctx, packages, labels)
