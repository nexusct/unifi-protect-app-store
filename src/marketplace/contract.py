"""Marketplace function contract + shared helpers.

A marketplace function is a single self-describing module: MANIFEST dict
(what it is, what it costs, what it needs) + a Function class implementing
process(camera, frame, ts, ctx). A scoped local Protect account connects the
on-site runtime; the loader instantiates the subscribed functions.
"""
import os
import re
import math
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar

from detectors import base as detector_base
from site_time import site_time

CATEGORIES = ["Retail & QSR", "Manufacturing & Warehouse", "Property & Liability",
              "Automotive & Parking", "Compliance", "People & Safety",
              "Healthcare & Senior Living", "Security & Access", "Intelligence"]
TIERS = ["starter", "pro", "enterprise"]
ID_PATTERN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
CONFIG_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
API_SURFACES = {"protect", "access"}
API_PRIMITIVES = {
    "protect": {"camera_inventory", "events", "rtsp_stream", "clip_export"},
    "access": {"developer_logs", "door_unlock"},
}
API_RUNNERS = {
    "protect": {"protect_event", "protect_stream", "protect_inventory", "protect_evidence"},
    "access": {"access_event", "access_unlock_request"},
}
API_PROFILES = {
    "camera_inventory", "event_metrics", "stream_quality", "scene_quality",
    "snapshot_capture", "snapshot_governance", "clip_export", "event_clip",
    "clip_governance", "clip_postprocess", "log_inventory", "log_aggregate",
    "log_audit", "log_sequence", "log_window", "log_quality", "audited_unlock",
}
API_EVENT_VALUE_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-_:][A-Za-z0-9]+)*")


def _is_safe_manifest_text(value, max_length):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        return False
    if len(value.splitlines()) != 1:
        return False
    for character in value:
        codepoint = ord(character)
        invalid_xml_character = (
            codepoint < 0x20
            or 0xD800 <= codepoint <= 0xDFFF
            or (codepoint & 0xFFFF) in (0xFFFE, 0xFFFF)
        )
        if invalid_xml_character:
            return False
    return True


class MarketplaceFunction:
    """Base class. ctx provides: alerts, site, access_events, settings."""

    name = None

    def __init__(self, settings: dict):
        self.settings = settings or {}

    def process(self, camera, frame, ts, ctx):  # pragma: no cover
        raise NotImplementedError


def validate_manifest(m: dict) -> list[str]:
    errs = []
    if not isinstance(m, dict):
        return ["manifest must be a dict"]
    for key in ("id", "name", "tagline", "category", "tier"):
        if not m.get(key):
            errs.append(f"missing {key}")

    function_id = m.get("id")
    if function_id and (not isinstance(function_id, str) or len(function_id) > 80 or not ID_PATTERN.fullmatch(function_id)):
        errs.append("id must be 1-80 lowercase letters/digits joined by hyphens or underscores")

    for key, max_length in (("name", 120), ("tagline", 300)):
        value = m.get(key)
        if value and not _is_safe_manifest_text(value, max_length):
            errs.append(f"{key} must be a single-line string up to {max_length} characters")

    if m.get("category") and (not isinstance(m["category"], str) or m["category"] not in CATEGORIES):
        errs.append(f"bad category {m['category']}")
    if m.get("tier") and (not isinstance(m["tier"], str) or m["tier"] not in TIERS):
        errs.append(f"bad tier {m['tier']}")
    if "requires_gpu" in m and not isinstance(m["requires_gpu"], bool):
        errs.append("requires_gpu must be a boolean")

    api = m.get("api")
    if api is not None:
        if not isinstance(api, dict):
            errs.append("api must be a dict")
        else:
            allowed_keys = {
                "surface", "primitive", "runner", "control",
                "event_types", "smart_types", "event_kinds", "mode", "profile",
            }
            unknown = sorted(set(api) - allowed_keys)
            if unknown:
                errs.append(f"unknown api fields {unknown}")
            surface = api.get("surface")
            primitive = api.get("primitive")
            runner = api.get("runner")
            control = api.get("control")
            if surface not in API_SURFACES:
                errs.append(f"bad api surface {surface!r}")
            elif primitive not in API_PRIMITIVES[surface]:
                errs.append(f"bad api primitive {primitive!r} for {surface}")
            if surface in API_RUNNERS and runner not in API_RUNNERS[surface]:
                errs.append(f"bad api runner {runner!r} for {surface}")
            if not isinstance(control, bool):
                errs.append("api control must be a boolean")
            expected_control = runner == "access_unlock_request"
            if isinstance(control, bool) and control != expected_control:
                errs.append("api control must be true only for access_unlock_request")
            if surface == "protect" and control is True:
                errs.append("Protect marketplace functions cannot perform control actions")
            for field in ("event_types", "smart_types", "event_kinds"):
                values = api.get(field, [])
                if not isinstance(values, list) or len(values) > 16:
                    errs.append(f"api {field} must be a list of at most 16 values")
                    continue
                if any(
                    not isinstance(value, str)
                    or not 1 <= len(value) <= 80
                    or not API_EVENT_VALUE_PATTERN.fullmatch(value)
                    for value in values
                ):
                    errs.append(f"api {field} contains an unsafe value")
                if len(values) != len(set(values)):
                    errs.append(f"api {field} contains duplicates")
            mode = api.get("mode", "event")
            if mode not in {"event", "after_hours", "threshold", "digest"}:
                errs.append(f"bad api mode {mode!r}")
            if api.get("profile") not in API_PROFILES:
                errs.append(f"bad api profile {api.get('profile')!r}")

    schema = m.get("config_schema", {})
    if not isinstance(schema, dict):
        errs.append("config_schema must be a dict")
    else:
        for key, description in schema.items():
            if not isinstance(key, str) or len(key) > 80 or not CONFIG_KEY_PATTERN.fullmatch(key):
                errs.append(f"bad config key {key!r}")
            if not _is_safe_manifest_text(description, 500):
                errs.append(f"config description for {key!r} must be a single-line string up to 500 characters")
    return errs


# ── shared helpers ──────────────────────────────────────────────

def in_zone(cx, cy, polygon):
    """Ray-casting point-in-polygon (normalized coords)."""
    if not polygon:
        return False
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


_model_cache = detector_base._models
_tracker_cache = OrderedDict()
_tracker_cache_lock = threading.RLock()
_TRACKER_CACHE_MAX = 512
_active_tracking_scope = ContextVar("marketplace_tracking_scope", default=None)


def current_tracking_scope():
    return _active_tracking_scope.get()


@contextmanager
def detection_scope(scope):
    token = _active_tracking_scope.set(scope)
    try:
        yield
    finally:
        _active_tracking_scope.reset(token)


def model(weights="yolov8n.pt", device=None):
    selected_device = device or os.environ.get("VISION_DEVICE", "cuda")
    return detector_base.get_model(weights, device=selected_device)


class CentroidTracker:
    """Small class-aware tracker isolated from mutable model predictor state."""

    def __init__(self, max_gap_seconds=None, max_distance=0.20):
        interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1"))
        self.max_gap_seconds = float(max_gap_seconds or max(3.0, interval * 3.0))
        self.max_distance = float(max_distance)
        self._next_id = 1
        self._tracks = {}

    def update(self, detections, now=None):
        observed_at = time.monotonic() if now is None else float(now)
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if observed_at - state["last_seen"] <= self.max_gap_seconds
        }

        assignments = {}
        candidate_pairs = []
        for detection_index, (cls, cx, cy) in enumerate(detections):
            for track_id, state in self._tracks.items():
                if state["class"] != cls:
                    continue
                distance = math.hypot(cx - state["cx"], cy - state["cy"])
                if distance <= self.max_distance:
                    candidate_pairs.append((distance, detection_index, track_id))

        used_tracks = set()
        for _, detection_index, track_id in sorted(candidate_pairs):
            if detection_index in assignments or track_id in used_tracks:
                continue
            assignments[detection_index] = track_id
            used_tracks.add(track_id)

        ids = []
        for index, (cls, cx, cy) in enumerate(detections):
            track_id = assignments.get(index)
            if track_id is None:
                track_id = self._next_id
                self._next_id += 1
            self._tracks[track_id] = {
                "class": cls,
                "cx": cx,
                "cy": cy,
                "last_seen": observed_at,
            }
            ids.append(track_id)
        return ids


def _tracker_for(weights, classes, tracking_scope):
    class_key = None if classes is None else tuple(sorted(int(value) for value in classes))
    scope = tracking_scope if tracking_scope is not None else current_tracking_scope()
    if scope is None:
        scope = ("thread", threading.get_ident())
    try:
        hash(scope)
    except TypeError:
        scope = repr(scope)
    key = (scope, weights, class_key)
    with _tracker_cache_lock:
        tracker = _tracker_cache.get(key)
        if tracker is None:
            tracker = CentroidTracker()
            _tracker_cache[key] = tracker
            while len(_tracker_cache) > _TRACKER_CACHE_MAX:
                _tracker_cache.popitem(last=False)
        else:
            _tracker_cache.move_to_end(key)
        return tracker


def _resolved_weights(weights, fallback="yolov8n.pt"):
    if os.path.isabs(weights) and not os.path.exists(weights):
        return fallback
    return weights


def boxes_of(frame, weights="yolov8n.pt", classes=None, conf=0.45, device=None,
             tracking_scope=None):
    """Return numeric class IDs and normalized box geometry with scoped IDs."""
    selected_weights = _resolved_weights(weights)
    selected_device = device or os.environ.get("VISION_DEVICE", "cuda")
    res = detector_base.run_inference(
        model(selected_weights, selected_device),
        frame,
        conf=conf,
        classes=classes,
    )
    h, wpx = frame.shape[:2]
    raw = []
    boxes = getattr(res, "boxes", None)
    for box in boxes if boxes is not None else []:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        cls = int(box.cls[0])
        x1n = max(0.0, min(1.0, x1 / wpx))
        y1n = max(0.0, min(1.0, y1 / h))
        x2n = max(0.0, min(1.0, x2 / wpx))
        y2n = max(0.0, min(1.0, y2 / h))
        raw.append((cls, (x1n + x2n) / 2, (y1n + y2n) / 2, x1n, y1n, x2n, y2n))
    tracker = _tracker_for(selected_weights, classes, tracking_scope)
    ids = tracker.update([(item[0], item[1], item[2]) for item in raw])
    return [(*item, track_id) for item, track_id in zip(raw, ids)]


def poses_of(frame, weights="yolov8n-pose.pt", conf=0.45, device=None,
             tracking_scope=None):
    """Return `(track_id, cx, cy, x1, y1, x2, y2, keypoints)` tuples."""
    selected_weights = _resolved_weights(weights, fallback="yolov8n-pose.pt")
    selected_device = device or os.environ.get("VISION_DEVICE", "cuda")
    result = detector_base.run_inference(
        model(selected_weights, selected_device), frame, conf=conf
    )
    boxes = getattr(result, "boxes", None)
    keypoints = getattr(result, "keypoints", None)
    if boxes is None or keypoints is None:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    classes = boxes.cls.cpu().numpy()
    points = keypoints.data.cpu().numpy()
    h, wpx = frame.shape[:2]
    count = min(len(xyxy), len(classes), len(points))
    raw = []
    for index in range(count):
        x1, y1, x2, y2 = xyxy[index]
        cls = int(classes[index])
        x1n = max(0.0, min(1.0, float(x1) / wpx))
        y1n = max(0.0, min(1.0, float(y1) / h))
        x2n = max(0.0, min(1.0, float(x2) / wpx))
        y2n = max(0.0, min(1.0, float(y2) / h))
        raw.append((cls, (x1n + x2n) / 2, (y1n + y2n) / 2, x1n, y1n, x2n, y2n, points[index]))
    tracker = _tracker_for(selected_weights, [0], tracking_scope)
    ids = tracker.update([(item[0], item[1], item[2]) for item in raw])
    return [
        (track_id, item[1], item[2], item[3], item[4], item[5], item[6], item[7])
        for item, track_id in zip(raw, ids)
    ]


def pixel_box(frame, x1, y1, x2, y2):
    """Convert normalized corners to clamped pixel slice coordinates."""
    h, wpx = frame.shape[:2]
    left = max(0, min(wpx, math.floor(float(x1) * wpx)))
    top = max(0, min(h, math.floor(float(y1) * h)))
    right = max(left, min(wpx, math.ceil(float(x2) * wpx)))
    bottom = max(top, min(h, math.ceil(float(y2) * h)))
    return left, top, right, bottom


class ZoneTracker:
    """Per-track-id zone dwell/approach state."""

    def __init__(self, max_gap_seconds=None):
        interval = float(os.environ.get("VISION_FRAME_INTERVAL", "1"))
        self.max_gap_seconds = float(max_gap_seconds or max(3.0, interval * 3.0))
        self.state = {}

    def update(self, key, inside: bool, ts: float):
        for stale_key, stale in list(self.state.items()):
            if stale_key != key and ts - stale.get("last_seen", ts) > self.max_gap_seconds:
                self.state.pop(stale_key, None)
        st = self.state.get(key)
        if st is None or ts - st.get("last_seen", ts) > self.max_gap_seconds:
            st = {"in": False, "since": None, "visits": [], "last_seen": ts}
            self.state[key] = st
        entered = inside and not st["in"]
        if entered:
            st["since"] = ts
            st["visits"].append(ts)
        dwell = (ts - st["since"]) if (inside and st["since"] is not None) else 0
        if not inside:
            st["since"] = None
        st["in"] = inside
        st["last_seen"] = ts
        return entered, dwell, st


def crossed_line(p_prev, p_now, line):
    """Direction-aware segment crossing. line = [(x1,y1),(x2,y2)] normalized."""
    (x1, y1), (x2, y2) = line

    def side(p):
        return (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)

    a, b = side(p_prev), side(p_now)
    if a == 0 or b == 0 or (a > 0) == (b > 0):
        return 0
    return 1 if a < 0 else -1
