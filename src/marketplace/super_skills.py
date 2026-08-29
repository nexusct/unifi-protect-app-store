"""Executable shared runtime for the 2026 marketplace super-skill portfolio.

The 30 public modules in :mod:`marketplace.functions` keep literal customer
contracts while this module owns bounded temporal state, cross-camera
correlation, anonymous flow ledgers, optional custom-model observation, access
and Protect event correlation, and evidence-package writing.

Privacy rules are deliberate: no face recognition, biometric identity, or
cross-camera re-identification is performed.  Cross-camera functions correlate
only anonymous class/time/camera observations.  Functions requiring domain
objects use customer-supplied weights and fail closed when those weights are
not available.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import threading
from collections import OrderedDict, defaultdict, deque
import numpy as np

from marketplace.access import (
    DENIED,
    DOOR_CLOSED,
    DOOR_STATE_ALARMS,
    GRANTED,
    AccessEventFeed,
    data_directory,
    describe,
    event_id,
    event_seconds,
    matches_door,
    prune_files,
    safe_component,
    write_package,
)
from marketplace.contract import MarketplaceFunction, boxes_of, crossed_line, in_zone, pixel_box, site_time
from marketplace.vendor_patterns import DomainObserver

PERSON_CLASS = 0
VEHICLE_CLASSES = {2, 3, 5, 7}

WORKFLOWS = (
    "secured_exit",
    "room_exit_sequence",
    "mobility_obstruction",
    "controlled_room_count",
    "occupancy_imbalance",
    "waiting_flow",
    "estate_health",
    "perimeter_verify",
    "intrusion_progression",
    "package_chain",
    "multi_camera_corroboration",
    "door_response",
    "zone_funnel",
    "queue_service",
    "curbside_handoff",
    "lane_balance",
    "table_reset",
    "traffic_trigger",
    "dock_turnaround",
    "trajectory_conflict",
    "domain_route",
    "persistent_obstruction",
    "domain_sequence",
    "yard_queue",
    "multi_class_flow",
    "space_utilization",
    "route_completion",
    "schedule_baseline",
    "shift_flow",
    "evidence_casebook",
)

_SHARED_LOCK = threading.RLock()
_SHARED_STATE: OrderedDict[tuple[str, str], dict] = OrderedDict()
_SHARED_LIMIT = 256
_CONFLICT_TRACKS_PER_CLASS = 64
_CONFLICT_PAIR_LIMIT = _CONFLICT_TRACKS_PER_CLASS ** 2


def _seconds(value) -> float:
    try:
        if hasattr(value, "timestamp"):
            return float(value.timestamp())
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _number(value, default, minimum, maximum) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    return max(float(minimum), min(float(maximum), parsed))


def _integer(value, default, minimum, maximum) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), min(int(maximum), parsed))


def _strings(value, default=()):
    selected = default if value is None else value
    if isinstance(selected, str):
        selected = selected.split(",")
    try:
        return [str(item).strip().lower() for item in selected if str(item).strip()]
    except TypeError:
        return [str(item).strip().lower() for item in default if str(item).strip()]


def _camera_id(camera) -> str:
    return str((camera or {}).get("id") or (camera or {}).get("name") or "camera")[:120]


def _point(item) -> tuple[float, float]:
    return float(item.get("cx", 0.0)), float(item.get("cy", 0.0))


def _track_key(item) -> str:
    return f"{item.get('class_id', item.get('label', 'object'))}:{item.get('track_id', 0)}"


def _distance(a, b) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _percentile(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bounded_append(queue, value, limit=2000):
    queue.append(value)
    while len(queue) > int(limit):
        queue.popleft()


def _event_type(event) -> str:
    for key in ("type", "event_type", "eventType", "modelKey", "kind", "name"):
        value = (event or {}).get(key)
        if value:
            return str(value).strip().lower()[:80]
    return "event"


def _protect_event_seconds(event, fallback=0.0) -> float:
    for key in ("timestamp", "start", "startTime", "createdAt", "time"):
        value = (event or {}).get(key)
        if value is None:
            continue
        try:
            if isinstance(value, str):
                from datetime import datetime

                return float(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return numeric
        except (TypeError, ValueError, OverflowError):
            continue
    return float(fallback)


def _redacted_protect_event(event, fallback_ts=0.0):
    camera_id = (
        (event or {}).get("camera_id")
        or (event or {}).get("cameraId")
        or ((event or {}).get("camera") or {}).get("id")
        or ""
    )
    raw_id = str((event or {}).get("id") or "")
    return {
        "event_id": hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16] if raw_id else "",
        "event_type": _event_type(event),
        "camera_id": str(camera_id)[:120],
        "timestamp": _protect_event_seconds(event, fallback_ts),
    }


class SuperSkillFunction(MarketplaceFunction):
    """One tested, bounded runtime shared by 30 literal marketplace contracts."""

    function_id = "super-skill"
    workflow = ""
    profile = {}

    def __init__(self, settings):
        merged = dict(type(self).profile or {})
        merged.update(settings or {})
        super().__init__(merged)
        self.settings = merged
        self.name = type(self).function_id
        self._started_at = None
        self._state = {}
        self._tracks = {}
        self._aggregates = defaultdict(int)
        self._samples = deque()
        self._access_feeds = {}
        self._seen_protect = OrderedDict()
        self._domain = DomainObserver(merged)

    def process(self, camera, frame, ts, ctx):
        if self.workflow not in WORKFLOWS:
            raise ValueError(f"unsupported super-skill workflow: {self.workflow!r}")
        now = _seconds(ts)
        if self._started_at is None:
            self._started_at = now
        method = getattr(self, f"_process_{self.workflow}")
        result = method(camera or {}, frame, now, ctx)
        self._prune_local(now)
        return result

    # -- shared helpers -------------------------------------------------

    def _zone(self, camera, logical_name):
        runtime_name = (self.settings.get("zones") or {}).get(logical_name)
        runtime_name = runtime_name or (type(self).profile.get("zones") or {}).get(logical_name)
        runtime_name = runtime_name or logical_name
        return ((camera or {}).get("zones") or {}).get(runtime_name)

    def _line(self, camera, logical_name):
        value = self._zone(camera, logical_name)
        return value if isinstance(value, (list, tuple)) and len(value) == 2 else None

    def _classes(self, default):
        values = self.settings.get("classes", default)
        if isinstance(values, str):
            values = [part.strip() for part in values.split(",") if part.strip()]
        try:
            return {int(value) for value in values}
        except (TypeError, ValueError):
            return set(default)

    def _box_items(self, camera, frame, classes=None):
        selected = None if classes is None else sorted(set(int(value) for value in classes))
        observations = boxes_of(
            frame,
            weights=str(self.settings.get("weights") or "yolov8n.pt"),
            classes=selected,
            conf=_number(self.settings.get("confidence"), 0.45, 0.05, 0.99),
            device=self.settings.get("device"),
            tracking_scope=(self.function_id, _camera_id(camera), tuple(selected or ())),
        )
        return [
            {
                "class_id": int(cls),
                "cx": float(cx),
                "cy": float(cy),
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "track_id": int(track_id),
            }
            for cls, cx, cy, x1, y1, x2, y2, track_id in observations
        ]

    def _domain_items(self, frame, ts):
        return self._domain.observe(frame, ts)

    def _inside(self, item, zone) -> bool:
        cx, cy = _point(item)
        return bool(zone and in_zone(cx, cy, zone))

    def _crossed(self, previous, current, line, direction="any") -> bool:
        if previous is None or current is None or not line:
            return False
        observed = crossed_line(previous, current, line)
        selected = str(direction or "any").strip().lower()
        if selected == "any":
            return observed != 0
        if selected in {"positive", "inbound", "top_to_bottom", "right_to_left", "1"}:
            return observed > 0
        if selected in {"negative", "outbound", "bottom_to_top", "left_to_right", "-1"}:
            return observed < 0
        return False

    def _fire(self, camera, frame, ctx, title, detail, meta):
        privacy_modes = {
            str(self.settings.get("privacy_mode") or "").strip().lower(),
            str(camera.get("privacy_mode") or "").strip().lower(),
        }
        snapshot = None if "skeleton" in privacy_modes else frame
        clean_meta = {
            str(key)[:80]: value
            for key, value in (meta or {}).items()
            if "actor" not in str(key).lower() and "face" not in str(key).lower()
        }
        return ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=self.function_id,
            title=title,
            detail=detail,
            frame=snapshot,
            meta=clean_meta,
        )

    def _digest_due(self, now, seconds, key="last_digest") -> bool:
        interval = _number(seconds, 300, 1, 86400)
        last = self._state.get(key)
        if last is None:
            self._state[key] = now
            return False
        if now - float(last) < interval:
            return False
        self._state[key] = now
        return True

    def _recent_access(self, ctx, now, door_id=None, window=30.0):
        candidates = []
        for event in reversed(list(getattr(ctx, "access_events", []) or [])):
            observed = event_seconds(event)
            if now - observed > float(window):
                break
            if door_id and not matches_door(event, door_id):
                continue
            candidates.append(event)
        return candidates

    def _poll_access(self, ctx, now, kinds, door_id=None, window=60.0):
        selected = tuple(sorted(set(kinds or ())))
        key = (str(door_id or ""), selected)
        feed = self._access_feeds.get(key)
        if feed is None:
            feed = AccessEventFeed(door_id=door_id, kinds=selected)
            self._access_feeds[key] = feed
        return feed.poll(ctx, now, window)

    def _new_protect_events(self, ctx, now, window=120.0, camera_id=None):
        accepted = []
        for event in list(getattr(ctx, "protect_events", []) or []):
            observed = _protect_event_seconds(event, now)
            if now - observed > float(window) or observed - now > 5.0:
                continue
            record = _redacted_protect_event(event, now)
            if camera_id and record["camera_id"] and record["camera_id"] != str(camera_id):
                continue
            key = record["event_id"] or hashlib.sha256(
                json.dumps(record, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            if key in self._seen_protect:
                continue
            self._seen_protect[key] = now
            accepted.append(record)
        while len(self._seen_protect) > 1024:
            self._seen_protect.popitem(last=False)
        return accepted

    def _shared_key(self, ctx):
        return self.function_id, str(getattr(ctx, "site", "site"))[:120]

    def _shared(self, ctx, now):
        key = self._shared_key(ctx)
        with _SHARED_LOCK:
            state = _SHARED_STATE.get(key)
            if state is None:
                state = {"updated_at": now}
                _SHARED_STATE[key] = state
            else:
                state["updated_at"] = now
                _SHARED_STATE.move_to_end(key)
            stale_before = now - 172800.0
            for old_key, old_state in list(_SHARED_STATE.items()):
                if len(_SHARED_STATE) <= _SHARED_LIMIT and float(old_state.get("updated_at", now)) >= stale_before:
                    continue
                _SHARED_STATE.pop(old_key, None)
            return state

    def _is_closed(self, ctx, now):
        configured = self.settings.get("closed_hours", "22:00-06:00")
        local = site_time(now, ctx)
        hour = local.tm_hour + local.tm_min / 60.0
        if isinstance(configured, (list, tuple)) and len(configured) == 2:
            start, end = float(configured[0]), float(configured[1])
        else:
            try:
                left, right = str(configured).split("-", 1)
                sh, sm = [int(value) for value in left.split(":", 1)]
                eh, em = [int(value) for value in right.split(":", 1)]
                start, end = sh + sm / 60.0, eh + em / 60.0
            except (TypeError, ValueError):
                start, end = 22.0, 6.0
        if start == end:
            return True
        return start <= hour < end if start < end else hour >= start or hour < end

    def _in_windows(self, ctx, now, value):
        windows = value or []
        if isinstance(windows, str):
            windows = [part.strip() for part in windows.split(",") if part.strip()]
        local = site_time(now, ctx)
        minute = local.tm_hour * 60 + local.tm_min
        for window in windows:
            try:
                left, right = str(window).split("-", 1)
                sh, sm = [int(value) for value in left.split(":", 1)]
                eh, em = [int(value) for value in right.split(":", 1)]
                start, end = sh * 60 + sm, eh * 60 + em
            except (TypeError, ValueError):
                continue
            if start <= end and start <= minute <= end:
                return True
            if start > end and (minute >= start or minute <= end):
                return True
        return False

    def _prune_local(self, now):
        maximum_age = _number(self.settings.get("state_ttl_seconds"), 7200, 60, 172800)
        for mapping in (self._tracks,):
            stale = [
                key
                for key, value in mapping.items()
                if now - float((value or {}).get("last", now)) > maximum_age
            ]
            for key in stale:
                mapping.pop(key, None)
            if len(mapping) > 2048:
                ordered = sorted(mapping, key=lambda key: float(mapping[key].get("last", 0.0)))
                for key in ordered[: len(mapping) - 2048]:
                    mapping.pop(key, None)

    def _sequence_update(self, key, point, zones, now, window):
        state = self._tracks.setdefault(key, {"stage": 0, "started": now, "last": now})
        if now - float(state.get("started", now)) > float(window):
            state = {"stage": 0, "started": now, "last": now}
            self._tracks[key] = state
        else:
            state["last"] = now
        stage = int(state.get("stage", 0))
        if stage < len(zones) and zones[stage] and in_zone(point[0], point[1], zones[stage]):
            state["stage"] = stage + 1
            state.setdefault("stage_times", []).append(now)
            if stage == 0:
                state["started"] = now
            return state["stage"] == len(zones), False, state
        for index in range(stage + 1, len(zones)):
            if zones[index] and in_zone(point[0], point[1], zones[index]):
                state["skipped"] = True
                state["out_of_order_at"] = now
                return False, True, state
        return False, False, state

    # -- 30 workflow implementations ----------------------------------

    def _process_secured_exit(self, camera, frame, now, ctx):
        zone = self._zone(camera, "approach")
        line = self._line(camera, "exit_line")
        hold = _number(self.settings.get("approach_seconds"), 8, 0, 3600)
        direction = self.settings.get("direction", "any")
        door_id = self.settings.get("door_id")
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            point = _point(item)
            inside = self._inside(item, zone)
            if inside and state.get("approach_since") is None:
                state["approach_since"] = now
            if not inside:
                state.pop("approach_since", None)
                state["alerted"] = False
            crossed = self._crossed(state.get("point"), point, line, direction)
            state.update(point=point, last=now)
            dwell = now - float(state.get("approach_since", now))
            if not state.get("alerted") and inside and (crossed or dwell >= hold):
                recent = self._recent_access(ctx, now, door_id, 30)
                state["alerted"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Secured exit approach observed",
                    "Anonymous movement met the configured secured-exit approach rule; review access context before action.",
                    {"approach_seconds": round(dwell, 1), "line_crossed": crossed, "access_events": len(recent)},
                )
        return None

    def _process_room_exit_sequence(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("bed", "transition", "doorway")]
        window = _number(self.settings.get("sequence_window_seconds"), 90, 2, 3600)
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            complete, skipped, state = self._sequence_update(_track_key(item), _point(item), zones, now, window)
            if complete and not state.get("reported"):
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Room exit sequence ready for review",
                    "Anonymous movement progressed through the configured room-exit zones; this is not a clinical determination.",
                    {"sequence_seconds": round(now - float(state.get("started", now)), 1), "zone_skipped": bool(skipped or state.get("skipped"))},
                )
        return None

    def _process_mobility_obstruction(self, camera, frame, now, ctx):
        zone = self._zone(camera, "egress")
        hold = _number(self.settings.get("hold_seconds"), 20, 1, 7200)
        allowed = set(
            _strings(
                self.settings.get("labels"),
                ["wheelchair", "walker", "mobility-aid"],
            )
        )
        for item in self._domain_items(frame, now):
            if allowed and str(item.get("label", "")).lower() not in allowed:
                continue
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            if self._inside(item, zone):
                state.setdefault("since", now)
                state["last"] = now
                if not state.get("alerted") and now - float(state["since"]) >= hold:
                    state["alerted"] = True
                    return self._fire(
                        camera,
                        frame,
                        ctx,
                        "Mobility aid remains in an egress zone",
                        "A configured mobility-aid class persisted in the egress polygon; verify safe passage manually.",
                        {"object_class": str(item.get("label", "object"))[:80], "duration_seconds": round(now - float(state["since"]), 1)},
                    )
            else:
                state.pop("since", None)
                state["alerted"] = False
        return None

    def _process_controlled_room_count(self, camera, frame, now, ctx):
        door_id = self.settings.get("door_id")
        observe = _number(self.settings.get("observe_seconds"), 15, 1, 300)
        expected = _integer(self.settings.get("expected_persons"), 2, 1, 20)
        for _, _, event in self._poll_access(
            ctx, now, {GRANTED}, door_id=door_id, window=observe + 10
        ):
            key = event_id(event)
            windows = self._state.setdefault("windows", {})
            windows[key] = {
                "started": now,
                "tracks": set(),
                "event": describe(event),
            }
            while len(windows) > 512:
                windows.pop(next(iter(windows)), None)
        zone = self._zone(camera, "door")
        people = self._box_items(camera, frame, {PERSON_CLASS})
        windows = self._state.setdefault("windows", {})
        for state in windows.values():
            for item in people:
                if self._inside(item, zone):
                    state["tracks"].add(_track_key(item))
        for key, state in list(windows.items()):
            if now - float(state["started"]) < observe:
                continue
            observed = len(state["tracks"])
            windows.pop(key, None)
            return self._fire(
                camera,
                frame,
                ctx,
                "Controlled-room count review complete",
                "A credential event was correlated with an anonymous visual count; policy and authorization still require human review.",
                {"expected_count": expected, "observed_count": observed, "count_matches": observed == expected},
            )
        return None

    def _process_occupancy_imbalance(self, camera, frame, now, ctx):
        zone_a = self._zone(camera, "zone_a")
        zone_b = self._zone(camera, "zone_b")
        counts = [0, 0]
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            counts[0] += int(self._inside(item, zone_a))
            counts[1] += int(self._inside(item, zone_b))
        difference = abs(counts[0] - counts[1])
        threshold = _integer(self.settings.get("imbalance_threshold"), 4, 1, 100)
        hold = _number(self.settings.get("hold_seconds"), 30, 1, 7200)
        if difference >= threshold:
            self._state.setdefault("imbalance_since", now)
        else:
            self._state.pop("imbalance_since", None)
            self._state["imbalance_alerted"] = False
        since = self._state.get("imbalance_since")
        if since is not None and not self._state.get("imbalance_alerted") and now - float(since) >= hold:
            self._state["imbalance_alerted"] = True
            return self._fire(
                camera,
                frame,
                ctx,
                "Care-area occupancy imbalance observed",
                "Anonymous counts between the two configured care areas exceeded the review threshold.",
                {"zone_a_count": counts[0], "zone_b_count": counts[1], "duration_seconds": round(now - float(since), 1)},
            )
        return None

    def _process_waiting_flow(self, camera, frame, now, ctx):
        names = ("arrival", "waiting", "service", "exit")
        zones = [self._zone(camera, name) for name in names]
        stale = _number(self.settings.get("abandonment_seconds"), 900, 30, 86400)
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"stage": -1, "last": now})
            state["last"] = now
            for index, zone in enumerate(zones):
                if zone and self._inside(item, zone) and index > int(state.get("stage", -1)):
                    state["stage"] = index
                    state.setdefault("stage_times", {})[index] = now
                    if index == 0:
                        self._aggregates["arrivals"] += 1
                    if index == 2:
                        self._aggregates["served"] += 1
                        start = state.get("stage_times", {}).get(1, state.get("stage_times", {}).get(0, now))
                        _bounded_append(self._samples, now - float(start))
                    if index == 3:
                        self._aggregates["exits"] += 1
                    break
        for state in self._tracks.values():
            if state.get("stage") in (0, 1) and not state.get("abandoned") and now - float(state.get("last", now)) >= stale:
                state["abandoned"] = True
                self._aggregates["abandoned"] += 1
        if self._digest_due(now, self.settings.get("digest_seconds", 300)) and self._aggregates["arrivals"]:
            waits = list(self._samples)
            result = self._fire(
                camera,
                frame,
                ctx,
                "Waiting-room flow ledger",
                "Anonymous arrivals, service transitions, exits, and reviewable abandonment candidates were summarized.",
                {
                    "arrivals": self._aggregates["arrivals"],
                    "served": self._aggregates["served"],
                    "exits": self._aggregates["exits"],
                    "abandonment_candidates": self._aggregates["abandoned"],
                    "median_wait_seconds": round(statistics.median(waits), 1) if waits else 0.0,
                },
            )
            self._aggregates.clear()
            self._samples.clear()
            return result
        return None

    def _frame_metrics(self, frame):
        if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            return {"luma": 0.0, "black_ratio": 1.0, "blur": 0.0, "signature": "missing"}
        gray = np.asarray(frame)
        if gray.ndim == 3:
            gray = gray[..., :3].mean(axis=2)
        gray = gray.astype(np.float32, copy=False)
        luma = float(gray.mean()) if gray.size else 0.0
        black_ratio = float((gray < 8).mean()) if gray.size else 1.0
        try:
            import cv2

            blur = float(cv2.Laplacian(gray.astype(np.uint8), cv2.CV_64F).var())
            small = cv2.resize(gray.astype(np.uint8), (16, 16), interpolation=cv2.INTER_AREA)
        except Exception:
            blur = float(np.var(np.diff(gray, axis=0))) if gray.shape[0] > 1 else 0.0
            small = gray[:: max(1, gray.shape[0] // 16), :: max(1, gray.shape[1] // 16)][:16, :16]
        signature = hashlib.blake2s(np.asarray(small).tobytes(), digest_size=8).hexdigest()
        return {"luma": luma, "black_ratio": black_ratio, "blur": blur, "signature": signature}

    def _process_estate_health(self, camera, frame, now, ctx):
        metrics = self._frame_metrics(frame)
        camera_id = _camera_id(camera)
        state = self._shared(ctx, now)
        with _SHARED_LOCK:
            cameras = state.setdefault("cameras", {})
            current = cameras.setdefault(camera_id, {})
            if current.get("signature") == metrics["signature"]:
                current.setdefault("frozen_since", now)
            else:
                current.pop("frozen_since", None)
            current.update(metrics, last_seen=now, name=str(camera.get("name") or ""), source=bool(camera.get("rtsp") or camera.get("url")))
            digest = _number(self.settings.get("digest_seconds"), 120, 10, 86400)
            if now - float(state.get("last_digest", 0.0)) < digest:
                return None
            state["last_digest"] = now
            configured = list(getattr(ctx, "cameras", []) or [])
            configured_ids = set()
            for configured_camera in configured:
                configured_id = _camera_id(configured_camera)
                configured_ids.add(configured_id)
                cameras.setdefault(configured_id, {"last_seen": self._started_at or now, "name": str(configured_camera.get("name") or ""), "source": bool(configured_camera.get("rtsp") or configured_camera.get("url"))})
            for stale_id, stale_state in list(cameras.items()):
                if stale_id not in configured_ids and now - float(stale_state.get("last_seen", now)) > 172800:
                    cameras.pop(stale_id, None)
            if len(cameras) > 2048:
                oldest = sorted(
                    cameras,
                    key=lambda item: float(cameras[item].get("last_seen", 0.0)),
                )
                for stale_id in oldest[: len(cameras) - 2048]:
                    cameras.pop(stale_id, None)
            startup = _number(self.settings.get("startup_grace_seconds"), 60, 0, 3600)
            offline_after = _number(self.settings.get("offline_seconds"), 90, 5, 86400)
            issues = {
                "offline": [],
                "unnamed": [],
                "missing_source": [],
                "black": [],
                "blurry": [],
                "frozen": [],
            }
            for cid, item in cameras.items():
                if now - float(item.get("last_seen", now)) > offline_after and now - float(self._started_at or now) >= startup:
                    issues["offline"].append(cid)
                if not str(item.get("name") or "").strip():
                    issues["unnamed"].append(cid)
                if not item.get("source"):
                    issues["missing_source"].append(cid)
                if float(item.get("black_ratio", 0.0)) >= _number(self.settings.get("black_ratio"), 0.98, 0.5, 1.0):
                    issues["black"].append(cid)
                if item.get("blur") is not None and float(item.get("blur", 9999.0)) < _number(self.settings.get("blur_threshold"), 15, 0, 10000):
                    issues["blurry"].append(cid)
                if item.get("frozen_since") is not None and now - float(item["frozen_since"]) >= _number(self.settings.get("freeze_seconds"), 30, 5, 3600):
                    issues["frozen"].append(cid)
        failure_count = len(getattr(ctx, "detector_failures", {}) or {})
        issue_count = sum(len(values) for values in issues.values()) + failure_count
        if not issue_count:
            return None
        return self._fire(
            camera,
            frame,
            ctx,
            "Vision estate health exceptions",
            "Camera and analytics health checks found reviewable exceptions; this consolidates operational diagnostics, not service guarantees.",
            {**{f"{key}_count": len(value) for key, value in issues.items()}, "detector_failure_count": failure_count, "camera_count": len(state.get("cameras", {}))},
        )

    def _process_perimeter_verify(self, camera, frame, now, ctx):
        zone = self._zone(camera, "perimeter")
        line = self._line(camera, "boundary")
        hold = _number(self.settings.get("hold_seconds"), 4, 0, 600)
        recent_protect = self._new_protect_events(ctx, now, self.settings.get("protect_window_seconds", 30), _camera_id(camera))
        classes = self._classes({PERSON_CLASS, *VEHICLE_CLASSES})
        for item in self._box_items(camera, frame, classes):
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            point = _point(item)
            if self._inside(item, zone):
                state.setdefault("inside_since", now)
            else:
                state.pop("inside_since", None)
                state["reported"] = False
            crossed = self._crossed(state.get("point"), point, line, self.settings.get("direction", "any"))
            state.update(point=point, last=now)
            dwell = now - float(state.get("inside_since", now))
            if not state.get("reported") and self._inside(item, zone) and (crossed or dwell >= hold) and (recent_protect or not self.settings.get("require_protect_event", False)):
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Perimeter event visually verified",
                    "Anonymous person or vehicle activity matched the configured perimeter rule and available Protect context.",
                    {"object_class": int(item.get("class_id", -1)), "line_crossed": crossed, "protect_events": len(recent_protect), "dwell_seconds": round(dwell, 1)},
                )
        return None

    def _process_intrusion_progression(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("perimeter", "yard", "doorway")]
        window = _number(self.settings.get("progression_seconds"), 120, 5, 3600)
        for item in self._box_items(camera, frame, self._classes({PERSON_CLASS, *VEHICLE_CLASSES})):
            complete, skipped, state = self._sequence_update(_track_key(item), _point(item), zones, now, window)
            if complete and not state.get("reported"):
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Multi-zone intrusion progression",
                    "One anonymous track progressed through the configured perimeter, yard, and doorway zones.",
                    {"progression_seconds": round(now - float(state.get("started", now)), 1), "zone_skipped": bool(skipped or state.get("skipped"))},
                )
        return None

    def _process_package_chain(self, camera, frame, now, ctx):
        zone = self._zone(camera, "package")
        labels = set(
            _strings(
                self.settings.get("labels"),
                ["package", "parcel", "box"],
            )
        )
        count = sum(1 for item in self._domain_items(frame, now) if (not labels or str(item.get("label", "")).lower() in labels) and self._inside(item, zone))
        previous = self._state.get("package_count")
        self._state["package_count"] = count
        if previous is None or count == previous:
            return None
        delta = count - int(previous)
        recent = self._recent_access(ctx, now, self.settings.get("door_id"), self.settings.get("access_window_seconds", 45))
        if self.settings.get("require_access_event", True) and not recent:
            return None
        return self._fire(
            camera,
            frame,
            ctx,
            "Package-room chain change",
            "The anonymous package count changed near an access event; review the deposit or pickup chain manually.",
            {"change": "deposit" if delta > 0 else "pickup", "count_delta": delta, "package_count": count, "access_events": len(recent)},
        )

    def _process_multi_camera_corroboration(self, camera, frame, now, ctx):
        if not self._is_closed(ctx, now):
            return None
        zone = self._zone(camera, "monitored")
        window = _number(self.settings.get("corroboration_seconds"), 45, 2, 600)
        camera_id = _camera_id(camera)
        items = [item for item in self._box_items(camera, frame, self._classes({PERSON_CLASS, *VEHICLE_CLASSES})) if not zone or self._inside(item, zone)]
        if not items:
            return None
        state = self._shared(ctx, now)
        with _SHARED_LOCK:
            observations = state.setdefault("observations", deque())
            while observations and now - float(observations[0][0]) > window:
                observations.popleft()
            reported = state.setdefault("reported", {})
            for marker, reported_at in list(reported.items()):
                if now - float(reported_at) > window:
                    reported.pop(marker, None)
            for item in items:
                cls = int(item.get("class_id", -1))
                match = next((entry for entry in observations if entry[1] != camera_id and entry[2] == cls), None)
                _bounded_append(observations, (now, camera_id, cls), 4096)
                if match:
                    pair = tuple(sorted((camera_id, match[1])))
                    marker = f"{pair}:{cls}"
                    if now - float(reported.get(marker, 0.0)) < window:
                        continue
                    reported[marker] = now
                    while len(reported) > 2048:
                        reported.pop(next(iter(reported)), None)
                    return self._fire(
                        camera,
                        frame,
                        ctx,
                        "After-hours activity corroborated",
                        "The same anonymous object class was observed on two distinct cameras within the configured after-hours window; no identity matching was used.",
                        {"camera_count": 2, "object_class": cls, "corroboration_seconds": round(now - float(match[0]), 1)},
                    )
        return None

    def _process_door_response(self, camera, frame, now, ctx):
        door_id = self.settings.get("door_id")
        timeout = _number(self.settings.get("response_timeout_seconds"), 180, 5, 3600)
        kinds = set(DOOR_STATE_ALARMS) | {DOOR_CLOSED}
        incidents = self._state.setdefault("incidents", OrderedDict())
        for observed_at, event_type, event in self._poll_access(
            ctx, now, kinds, door_id=door_id, window=timeout + 60
        ):
            if event_type in DOOR_STATE_ALARMS:
                incidents[event_id(event)] = {
                    "started": observed_at,
                    "alarm_type": event_type,
                    "responded": None,
                }
                while len(incidents) > 512:
                    incidents.popitem(last=False)
            elif event_type == DOOR_CLOSED:
                for state in reversed(list(incidents.values())):
                    if not state.get("closed"):
                        state["closed"] = observed_at
                        break
        response_zone = self._zone(camera, "response")
        people_present = any(self._inside(item, response_zone) for item in self._box_items(camera, frame, {PERSON_CLASS}))
        for key, state in list(incidents.items()):
            if people_present and state.get("responded") is None:
                state["responded"] = now
            elapsed = now - float(state["started"])
            if state.get("closed") is None and elapsed < timeout:
                continue
            incidents.pop(key, None)
            return self._fire(
                camera,
                frame,
                ctx,
                "Door-alarm response review",
                "A door alarm was correlated with anonymous observed response timing and door-close state.",
                {
                    "alarm_type": state["alarm_type"],
                    "response_seconds": round(float(state["responded"]) - float(state["started"]), 1) if state.get("responded") else None,
                    "closed": state.get("closed") is not None,
                    "timed_out": state.get("closed") is None,
                },
            )
        return None

    def _process_zone_funnel(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("entrance", "display", "product", "checkout")]
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"stage": -1, "last": now})
            state["last"] = now
            for index, zone in enumerate(zones):
                if zone and self._inside(item, zone) and index > int(state.get("stage", -1)):
                    state["stage"] = index
                    self._aggregates[f"stage_{index}"] += 1
                    break
        if self._digest_due(now, self.settings.get("digest_seconds", 300)) and self._aggregates:
            result = self._fire(
                camera,
                frame,
                ctx,
                "Anonymous zone funnel",
                "Anonymous zone-to-zone progression counts were summarized without identity or demographic inference.",
                {"entrance": self._aggregates["stage_0"], "display": self._aggregates["stage_1"], "product": self._aggregates["stage_2"], "checkout": self._aggregates["stage_3"]},
            )
            self._aggregates.clear()
            return result
        return None

    def _process_queue_service(self, camera, frame, now, ctx):
        arrival_line = self._line(camera, "arrival_line")
        queue_zone = self._zone(camera, "queue")
        service_zone = self._zone(camera, "service")
        exit_line = self._line(camera, "exit_line")
        for item in self._box_items(camera, frame, {PERSON_CLASS}):
            key = _track_key(item)
            point = _point(item)
            state = self._tracks.setdefault(key, {"last": now})
            if not state.get("arrived") and (self._inside(item, queue_zone) or self._crossed(state.get("point"), point, arrival_line, "any")):
                state.update(arrived=now, stage="queue")
                self._aggregates["arrivals"] += 1
            if state.get("arrived") is not None and not state.get("served") and self._inside(item, service_zone):
                state.update(served=now, stage="service")
                self._aggregates["served"] += 1
                _bounded_append(self._samples, now - float(state["arrived"]))
            if state.get("arrived") is not None and not state.get("served") and self._crossed(state.get("point"), point, exit_line, "any"):
                state["abandoned"] = True
                self._aggregates["abandoned"] += 1
            state.update(point=point, last=now)
        if self._digest_due(now, self.settings.get("digest_seconds", 300)) and self._aggregates["arrivals"]:
            waits = list(self._samples)
            result = self._fire(
                camera,
                frame,
                ctx,
                "Queue service-rate digest",
                "Anonymous queue arrivals, service starts, and abandonment candidates were summarized.",
                {"arrivals": self._aggregates["arrivals"], "served": self._aggregates["served"], "abandonment_candidates": self._aggregates["abandoned"], "p90_wait_seconds": round(_percentile(waits, 0.9), 1)},
            )
            self._aggregates.clear()
            self._samples.clear()
            return result
        return None

    def _process_curbside_handoff(self, camera, frame, now, ctx):
        arrival_zone = self._zone(camera, "arrival")
        handoff_zone = self._zone(camera, "handoff")
        departure_line = self._line(camera, "departure")
        max_wait = _number(self.settings.get("max_wait_seconds"), 300, 5, 7200)
        items = self._box_items(camera, frame, {PERSON_CLASS, *VEHICLE_CLASSES})
        people = [item for item in items if item["class_id"] == PERSON_CLASS and self._inside(item, handoff_zone)]
        for item in [value for value in items if value["class_id"] in VEHICLE_CLASSES]:
            key = _track_key(item)
            point = _point(item)
            state = self._tracks.setdefault(key, {"last": now})
            if self._inside(item, arrival_zone):
                state.setdefault("arrived", now)
            if state.get("arrived") is not None and people:
                state.setdefault("handoff", now)
            departed = self._crossed(state.get("point"), point, departure_line, "any")
            state.update(point=point, last=now)
            if state.get("arrived") is not None and not state.get("reported") and (departed or now - float(state["arrived"]) >= max_wait):
                state["reported"] = True
                completed = bool(departed and state.get("handoff") is not None)
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Curbside handoff review",
                    "Anonymous curbside arrival, handoff overlap, and departure timing were correlated.",
                    {"completed": completed, "wait_seconds": round(now - float(state["arrived"]), 1), "handoff_observed": state.get("handoff") is not None},
                )
        return None

    def _process_lane_balance(self, camera, frame, now, ctx):
        zones = [self._zone(camera, "lane_a"), self._zone(camera, "lane_b")]
        counts = [0, 0]
        for item in self._box_items(camera, frame, VEHICLE_CLASSES):
            for index, zone in enumerate(zones):
                counts[index] += int(self._inside(item, zone))
        threshold = _integer(self.settings.get("imbalance_count"), 2, 1, 100)
        hold = _number(self.settings.get("imbalance_seconds"), 60, 1, 7200)
        if abs(counts[0] - counts[1]) >= threshold:
            self._state.setdefault("imbalance_since", now)
        else:
            self._state.pop("imbalance_since", None)
            self._state["imbalance_alerted"] = False
        since = self._state.get("imbalance_since")
        if since is not None and not self._state.get("imbalance_alerted") and now - float(since) >= hold:
            self._state["imbalance_alerted"] = True
            return self._fire(
                camera,
                frame,
                ctx,
                "Drive-thru lane imbalance",
                "Anonymous vehicle counts remained imbalanced between the two configured lanes.",
                {"lane_a_count": counts[0], "lane_b_count": counts[1], "duration_seconds": round(now - float(since), 1)},
            )
        return None

    def _roi_signature(self, camera, frame, logical_zone):
        zone = self._zone(camera, logical_zone)
        if frame is None or not zone:
            return None
        xs = [float(point[0]) for point in zone]
        ys = [float(point[1]) for point in zone]
        left, top, right, bottom = pixel_box(frame, min(xs), min(ys), max(xs), max(ys))
        roi = np.asarray(frame)[top:bottom, left:right]
        if roi.size == 0:
            return None
        gray = roi[..., :3].mean(axis=2) if roi.ndim == 3 else roi
        return np.asarray(gray, dtype=np.float32)

    def _scene_change(self, previous, current):
        if previous is None or current is None or previous.shape != current.shape or previous.size == 0:
            return 0.0
        return float(np.mean(np.abs(previous - current)) / 255.0)

    def _process_table_reset(self, camera, frame, now, ctx):
        table_zone = self._zone(camera, "table")
        approach_zone = self._zone(camera, "service_approach")
        items = self._box_items(camera, frame, {PERSON_CLASS})
        occupied = any(self._inside(item, table_zone) for item in items)
        service_present = any(self._inside(item, approach_zone) for item in items)
        signature = self._roi_signature(camera, frame, "table")
        previous_occupied = bool(self._state.get("occupied"))
        self._state["occupied"] = occupied
        if previous_occupied and not occupied:
            self._state["vacant_since"] = now
            self._state["vacant_signature"] = signature
            self._state["reported"] = False
        if self._state.get("vacant_since") is None:
            return None
        change = self._scene_change(self._state.get("vacant_signature"), signature)
        if service_present and change >= _number(self.settings.get("scene_change_threshold"), 0.08, 0.0, 1.0):
            self._state.pop("vacant_since", None)
            self._state["reset_seconds"] = now
            return None
        delay = now - float(self._state["vacant_since"])
        if not self._state.get("reported") and delay >= _number(self.settings.get("reset_seconds"), 180, 5, 7200):
            self._state["reported"] = True
            return self._fire(
                camera,
                frame,
                ctx,
                "Table reset delay review",
                "A configured table remained vacant without the expected service-approach and scene-change pattern.",
                {"vacant_seconds": round(delay, 1), "service_activity_observed": service_present, "scene_change": round(change, 3)},
            )
        return None

    def _process_traffic_trigger(self, camera, frame, now, ctx):
        line = self._line(camera, "traffic_line")
        zone = self._zone(camera, "service")
        window = _number(self.settings.get("window_seconds"), 300, 5, 3600)
        threshold = _integer(self.settings.get("event_threshold"), 20, 1, 10000)
        times = self._state.setdefault("crossings", deque())
        for item in self._box_items(camera, frame, self._classes({PERSON_CLASS})):
            key = _track_key(item)
            point = _point(item)
            state = self._tracks.setdefault(key, {"last": now})
            crossed = self._crossed(state.get("point"), point, line, self.settings.get("direction", "any"))
            if crossed and (not zone or self._inside(item, zone)):
                _bounded_append(times, now, 10000)
            state.update(point=point, last=now)
        while times and now - float(times[0]) > window:
            times.popleft()
        if len(times) >= threshold and now - float(self._state.get("last_trigger", 0.0)) >= window:
            count = len(times)
            self._state["last_trigger"] = now
            times.clear()
            return self._fire(
                camera,
                frame,
                ctx,
                "High-traffic service trigger",
                "Anonymous crossings exceeded the configured service-review threshold within the rolling window.",
                {"crossings": count, "window_seconds": window},
            )
        return None

    def _process_dock_turnaround(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("arrival", "staging", "dock", "departure")]
        window = _number(self.settings.get("turnaround_seconds"), 7200, 60, 86400)
        stage_limit = _number(self.settings.get("stage_timeout_seconds"), 1800, 30, 86400)
        for item in self._box_items(camera, frame, VEHICLE_CLASSES):
            key = _track_key(item)
            complete, skipped, state = self._sequence_update(key, _point(item), zones, now, window)
            stage_times = state.get("stage_times", [])
            if len(stage_times) >= 2 and not state.get("timeout_reported") and now - float(stage_times[-1]) >= stage_limit:
                state["timeout_reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Dock stage delay review",
                    "An anonymous vehicle remained in a configured dock stage beyond the review threshold.",
                    {"stage": int(state.get("stage", 0)), "stage_seconds": round(now - float(stage_times[-1]), 1)},
                )
            if complete and not state.get("reported"):
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Dock turnaround sequence complete",
                    "Anonymous vehicle progression through arrival, staging, dock, and departure was timed.",
                    {"turnaround_seconds": round(now - float(state.get("started", now)), 1), "zone_skipped": bool(skipped or state.get("skipped"))},
                )
        return None

    def _process_trajectory_conflict(self, camera, frame, now, ctx):
        zone = self._zone(camera, "apron")
        hold = _number(self.settings.get("hold_seconds"), 1.5, 0, 60)
        threshold = _number(self.settings.get("conflict_distance_ratio"), 0.14, 0.01, 1.0)
        items = [item for item in self._box_items(camera, frame, {PERSON_CLASS, *VEHICLE_CLASSES}) if not zone or self._inside(item, zone)]
        people_items = sorted(
            (item for item in items if item.get("class_id") == PERSON_CLASS),
            key=_track_key,
        )[:_CONFLICT_TRACKS_PER_CLASS]
        vehicle_items = sorted(
            (item for item in items if item.get("class_id") in VEHICLE_CLASSES),
            key=_track_key,
        )[:_CONFLICT_TRACKS_PER_CLASS]
        current = {}
        for item in [*people_items, *vehicle_items]:
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            previous = state.get("point")
            point = _point(item)
            velocity = (0.0, 0.0) if previous is None else (point[0] - previous[0], point[1] - previous[1])
            state.update(point=point, velocity=velocity, last=now, class_id=item["class_id"])
            current[key] = state
        people = [(key, value) for key, value in current.items() if value["class_id"] == PERSON_CLASS]
        vehicles = [(key, value) for key, value in current.items() if value["class_id"] in VEHICLE_CLASSES]
        conflicts = self._state.get("conflicts")
        if not isinstance(conflicts, OrderedDict):
            conflicts = OrderedDict(conflicts or {})
            self._state["conflicts"] = conflicts
        reported_pairs = self._state.get("reported_pairs")
        if not isinstance(reported_pairs, OrderedDict):
            if isinstance(reported_pairs, dict):
                reported_pairs = OrderedDict(reported_pairs)
            else:
                reported_pairs = OrderedDict((pair, now) for pair in (reported_pairs or ()))
            self._state["reported_pairs"] = reported_pairs
        active_pairs = set()
        alert_payload = None
        for person_key, person in people:
            for vehicle_key, vehicle in vehicles:
                relative = (person["point"][0] - vehicle["point"][0], person["point"][1] - vehicle["point"][1])
                relative_velocity = (person["velocity"][0] - vehicle["velocity"][0], person["velocity"][1] - vehicle["velocity"][1])
                converging = relative[0] * relative_velocity[0] + relative[1] * relative_velocity[1] < 0
                pair = f"{person_key}|{vehicle_key}"
                if _distance(person["point"], vehicle["point"]) <= threshold and converging:
                    active_pairs.add(pair)
                    conflicts.setdefault(pair, now)
                    since = conflicts[pair]
                    if now - float(since) >= hold and pair not in reported_pairs:
                        reported_pairs[pair] = now
                        if alert_payload is None:
                            alert_payload = {
                                "distance_ratio": round(_distance(person["point"], vehicle["point"]), 3),
                                "hold_seconds": round(now - float(since), 1),
                            }
        for pair in list(conflicts):
            if pair not in active_pairs:
                conflicts.pop(pair, None)
                reported_pairs.pop(pair, None)
        while len(conflicts) > _CONFLICT_PAIR_LIMIT:
            pair, _ = conflicts.popitem(last=False)
            reported_pairs.pop(pair, None)
        for pair in list(reported_pairs):
            if pair not in conflicts:
                reported_pairs.pop(pair, None)
        while len(reported_pairs) > _CONFLICT_PAIR_LIMIT:
            reported_pairs.popitem(last=False)
        if alert_payload is not None:
            return self._fire(
                camera,
                frame,
                ctx,
                "Dock-apron conflict risk",
                "Anonymous person and vehicle tracks were close and converging in the configured apron zone.",
                alert_payload,
            )
        return None

    def _process_domain_route(self, camera, frame, now, ctx):
        allowed_zone = self._zone(camera, "allowed_corridor")
        line = self._line(camera, "direction_line")
        hold = _number(self.settings.get("off_route_seconds"), 4, 0, 600)
        labels = set(_strings(self.settings.get("labels"), ["forklift"]))
        for item in self._domain_items(frame, now):
            if labels and str(item.get("label", "")).lower() not in labels:
                continue
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            point = _point(item)
            outside = bool(allowed_zone and not self._inside(item, allowed_zone))
            wrong_way = self._crossed(state.get("point"), point, line, self.settings.get("forbidden_direction", "right_to_left"))
            if outside:
                state.setdefault("outside_since", now)
            else:
                state.pop("outside_since", None)
                state["reported"] = False
            state.update(point=point, last=now)
            duration = now - float(state.get("outside_since", now))
            if not state.get("reported") and (wrong_way or (outside and duration >= hold)):
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Forklift route deviation review",
                    "A customer-model forklift track left the allowed corridor or crossed the configured line in the forbidden direction.",
                    {"off_route": outside, "wrong_way": wrong_way, "duration_seconds": round(duration, 1)},
                )
        return None

    def _process_persistent_obstruction(self, camera, frame, now, ctx):
        zones = [self._zone(camera, "aisle"), self._zone(camera, "emergency_access")]
        hold = _number(self.settings.get("hold_seconds"), 45, 1, 7200)
        if self.settings.get("weights"):
            items = self._domain_items(frame, now)
        else:
            items = [item for item in self._box_items(camera, frame, None) if item.get("class_id") != PERSON_CLASS]
        for item in items:
            inside = any(zone and self._inside(item, zone) for zone in zones)
            key = _track_key(item)
            state = self._tracks.setdefault(key, {"last": now})
            if inside:
                state.setdefault("since", now)
            else:
                state.pop("since", None)
                state["reported"] = False
            state["last"] = now
            if inside and not state.get("reported") and now - float(state["since"]) >= hold:
                state["reported"] = True
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Aisle blockage duration review",
                    "A non-person object persisted in a configured aisle or emergency-access polygon.",
                    {"duration_seconds": round(now - float(state["since"]), 1), "object_class": str(item.get("label", item.get("class_id", "object")))[:80]},
                )
        return None

    def _process_domain_sequence(self, camera, frame, now, ctx):
        zone = self._zone(camera, "workcell")
        expected = _strings(
            self.settings.get("expected_sequence"),
            ["stage-a", "stage-b", "stage-c"],
        )
        if not expected:
            return None
        step_timeout = _number(self.settings.get("max_step_seconds"), 120, 1, 7200)
        for item in self._domain_items(frame, now):
            if zone and not self._inside(item, zone):
                continue
            label = str(item.get("label", "")).strip().lower()
            if label not in expected:
                continue
            key = str(item.get("track_id", "workcell"))
            state = self._tracks.setdefault(key, {"stage": 0, "started": now, "last_step": now, "last": now})
            state["last"] = now
            expected_label = expected[int(state.get("stage", 0))]
            if label == expected_label:
                state["stage"] += 1
                state["last_step"] = now
                if int(state["stage"]) == len(expected):
                    duration = now - float(state["started"])
                    state.update(stage=0, started=now, last_step=now)
                    return self._fire(
                        camera,
                        frame,
                        ctx,
                        "Cycle-step sequence complete",
                        "Customer-model stage labels completed the configured workcell sequence.",
                        {"cycle_seconds": round(duration, 1), "step_count": len(expected)},
                    )
            elif expected.index(label) > int(state.get("stage", 0)):
                skipped = expected_label
                state.update(stage=0, started=now, last_step=now)
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Cycle-step order review",
                    "A customer-model stage label appeared ahead of the configured expected step.",
                    {"expected_step": skipped, "observed_step": label},
                )
            if now - float(state.get("last_step", now)) >= step_timeout:
                state["last_step"] = now
                return self._fire(
                    camera,
                    frame,
                    ctx,
                    "Cycle-step duration review",
                    "The current configured workcell step exceeded its review threshold.",
                    {"expected_step": expected_label, "step_seconds": round(step_timeout, 1)},
                )
        return None

    def _process_yard_queue(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("queue", "staging", "dock")]
        counts = [0, 0, 0]
        for item in self._box_items(camera, frame, VEHICLE_CLASSES):
            for index, zone in enumerate(zones):
                counts[index] += int(self._inside(item, zone))
        _bounded_append(self._samples, tuple(counts), 1000)
        if not self._digest_due(now, self.settings.get("digest_seconds", 300)):
            return None
        if not self._samples:
            return None
        queue_peak = max(value[0] for value in self._samples)
        result = self._fire(
            camera,
            frame,
            ctx,
            "Yard queue bottleneck digest",
            "Anonymous vehicle counts across queue, staging, and dock zones were summarized.",
            {"queue_peak": queue_peak, "queue_median": round(statistics.median(value[0] for value in self._samples), 1), "staging_peak": max(value[1] for value in self._samples), "dock_peak": max(value[2] for value in self._samples), "spillback_candidate": queue_peak >= _integer(self.settings.get("spillback_threshold"), 6, 1, 1000)},
        )
        self._samples.clear()
        return result

    def _process_multi_class_flow(self, camera, frame, now, ctx):
        line = self._line(camera, "crossing_line")
        for item in self._box_items(camera, frame, self._classes({PERSON_CLASS, *VEHICLE_CLASSES})):
            key = _track_key(item)
            point = _point(item)
            state = self._tracks.setdefault(key, {"last": now})
            if self._crossed(state.get("point"), point, line, "left_to_right"):
                self._aggregates[f"class_{item['class_id']}_forward"] += 1
            if self._crossed(state.get("point"), point, line, "right_to_left"):
                self._aggregates[f"class_{item['class_id']}_reverse"] += 1
            state.update(point=point, last=now)
        if self._digest_due(now, self.settings.get("digest_seconds", 300)) and self._aggregates:
            result = self._fire(
                camera,
                frame,
                ctx,
                "Multi-class flow ledger",
                "Directional anonymous line crossings were summarized by object class.",
                {"counts": dict(sorted(self._aggregates.items())), "class_count": len({key.split('_')[1] for key in self._aggregates})},
            )
            self._aggregates.clear()
            return result
        return None

    def _process_space_utilization(self, camera, frame, now, ctx):
        zone = self._zone(camera, "space")
        count = sum(1 for item in self._box_items(camera, frame, {PERSON_CLASS}) if self._inside(item, zone))
        sample_seconds = _number(self.settings.get("sample_seconds"), 5, 1, 300)
        if now - float(self._state.get("last_sample", -sample_seconds)) >= sample_seconds:
            self._state["last_sample"] = now
            _bounded_append(self._samples, count, 5000)
        if self._digest_due(now, self.settings.get("digest_seconds", 900)) and self._samples:
            values = list(self._samples)
            result = self._fire(
                camera,
                frame,
                ctx,
                "Anonymous space-utilization percentiles",
                "Anonymous occupancy samples were summarized as utilization percentiles without identity tracking.",
                {"samples": len(values), "p50_occupancy": round(_percentile(values, 0.5), 1), "p90_occupancy": round(_percentile(values, 0.9), 1), "p95_occupancy": round(_percentile(values, 0.95), 1), "peak_occupancy": max(values)},
            )
            self._samples.clear()
            return result
        return None

    def _process_route_completion(self, camera, frame, now, ctx):
        zones = [self._zone(camera, name) for name in ("checkpoint_a", "checkpoint_b", "checkpoint_c", "checkpoint_d")]
        window = _number(self.settings.get("route_window_seconds"), 600, 10, 86400)
        for item in self._box_items(camera, frame, self._classes({PERSON_CLASS, *VEHICLE_CLASSES})):
            complete, skipped, state = self._sequence_update(_track_key(item), _point(item), zones, now, window)
            if int(state.get("stage", 0)) == 1 and not state.get("counted_start"):
                state["counted_start"] = True
                self._aggregates["started"] += 1
            if complete and not state.get("reported"):
                state["reported"] = True
                self._aggregates["completed"] += 1
                self._aggregates["skipped"] += int(
                    bool(skipped or state.get("skipped"))
                )
                _bounded_append(self._samples, now - float(state.get("started", now)))
        if self._digest_due(now, self.settings.get("digest_seconds", 600)) and self._aggregates["started"]:
            values = list(self._samples)
            result = self._fire(
                camera,
                frame,
                ctx,
                "Route completion ledger",
                "Anonymous route starts and ordered checkpoint completions were summarized.",
                {"started": self._aggregates["started"], "completed": self._aggregates["completed"], "skipped_zone_candidates": self._aggregates["skipped"], "median_completion_seconds": round(statistics.median(values), 1) if values else 0.0},
            )
            self._aggregates.clear()
            self._samples.clear()
            return result
        return None

    def _process_schedule_baseline(self, camera, frame, now, ctx):
        zone = self._zone(camera, "activity")
        count = sum(1 for item in self._box_items(camera, frame, self._classes({PERSON_CLASS, *VEHICLE_CLASSES})) if not zone or self._inside(item, zone))
        local = site_time(now, ctx)
        slot = local.tm_wday * 24 + local.tm_hour
        baselines = self._state.setdefault("baselines", defaultdict(lambda: deque(maxlen=200)))
        values = baselines[slot]
        minimum = _integer(self.settings.get("min_samples"), 12, 2, 200)
        threshold = _number(self.settings.get("change_threshold"), 2.5, 0.1, 100)
        hold = _number(self.settings.get("hold_seconds"), 30, 0, 3600)
        result = None
        if len(values) >= minimum:
            baseline = statistics.median(values)
            deviation = abs(count - baseline)
            if deviation >= threshold:
                self._state.setdefault("anomaly_since", now)
            else:
                self._state.pop("anomaly_since", None)
                self._state["baseline_alerted"] = False
            since = self._state.get("anomaly_since")
            if since is not None and not self._state.get("baseline_alerted") and now - float(since) >= hold:
                self._state["baseline_alerted"] = True
                result = self._fire(
                    camera,
                    frame,
                    ctx,
                    "Scheduled activity baseline exception",
                    "Anonymous activity differed from the learned hour-of-week baseline; review context before action.",
                    {"observed_count": count, "baseline_count": round(baseline, 1), "deviation": round(deviation, 1), "slot": slot},
                )
        values.append(count)
        return result

    def _process_shift_flow(self, camera, frame, now, ctx):
        if not self._in_windows(ctx, now, self.settings.get("shift_windows", ["06:30-08:30", "14:30-16:30", "22:30-00:30"])):
            return None
        zone = self._zone(camera, "shift")
        line = self._line(camera, "ingress_line")
        items = [item for item in self._box_items(camera, frame, {PERSON_CLASS, *VEHICLE_CLASSES}) if not zone or self._inside(item, zone)]
        people = []
        vehicles = []
        for item in items:
            key = _track_key(item)
            point = _point(item)
            state = self._tracks.setdefault(key, {"last": now})
            if self._crossed(state.get("point"), point, line, "left_to_right"):
                self._aggregates["ingress"] += 1
            if self._crossed(state.get("point"), point, line, "right_to_left"):
                self._aggregates["egress"] += 1
            state.update(point=point, last=now)
            (people if item["class_id"] == PERSON_CLASS else vehicles).append(point)
        overlap_distance = _number(self.settings.get("overlap_distance_ratio"), 0.12, 0.01, 1.0)
        if any(_distance(person, vehicle) <= overlap_distance for person in people for vehicle in vehicles):
            self._aggregates["person_vehicle_overlap_frames"] += 1
        if self._digest_due(now, self.settings.get("digest_seconds", 300)) and self._aggregates:
            result = self._fire(
                camera,
                frame,
                ctx,
                "Shift-change flow review",
                "Anonymous ingress, egress, and person-vehicle overlap observations were summarized for the configured shift window.",
                dict(self._aggregates),
            )
            self._aggregates.clear()
            return result
        return None

    def _process_evidence_casebook(self, camera, frame, now, ctx):
        collect = _number(self.settings.get("collect_seconds"), 20, 1, 600)
        door_id = self.settings.get("door_id")
        access_records = self._poll_access(
            ctx,
            now,
            set(DOOR_STATE_ALARMS) | {DENIED, GRANTED},
            door_id=door_id,
            window=collect + 120,
        )
        access_events = [event for _, _, event in access_records]
        protect_events = self._new_protect_events(ctx, now, collect + 120, _camera_id(camera))
        open_case = self._state.get("open_case")
        if (access_events or protect_events) and open_case is None:
            seed = f"{getattr(ctx, 'site', 'site')}|{_camera_id(camera)}|{now:.3f}|{self.function_id}"
            open_case = {
                "id": hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20],
                "started_at": now,
                "access_events": [],
                "protect_events": [],
                "max_people": 0,
            }
            self._state["open_case"] = open_case
        if open_case is None:
            return None
        open_case["access_events"].extend(describe(event, include_actor=False) for event in access_events)
        open_case["protect_events"].extend(protect_events)
        open_case["access_events"] = open_case["access_events"][-200:]
        open_case["protect_events"] = open_case["protect_events"][-200:]
        open_case["max_people"] = max(open_case["max_people"], len(self._box_items(camera, frame, {PERSON_CLASS})))
        if now - float(open_case["started_at"]) < collect:
            return None
        directory = data_directory("evidence-casebooks")
        package_name = f"{safe_component(getattr(ctx, 'site', 'site'))}-{safe_component(_camera_id(camera))}-{open_case['id']}"
        payload = {
            "schema": "nexus.vision-evidence-casebook/v1",
            "case_id": open_case["id"],
            "site": str(getattr(ctx, "site", "site"))[:120],
            "camera_id": _camera_id(camera),
            "started_at": open_case["started_at"],
            "closed_at": now,
            "access_events": open_case["access_events"][:200],
            "protect_events": open_case["protect_events"][:200],
            "anonymous_observations": {"max_people": open_case["max_people"]},
            "privacy": {"biometric_identity": False, "access_actor_included": False, "raw_frame_persisted": False},
        }
        path = write_package(directory, package_name, payload)
        prune_files(
            directory,
            "*.json",
            max_files=_integer(self.settings.get("max_cases"), 500, 1, 100000),
            retention_days=_integer(self.settings.get("retention_days"), 30, 1, 3650),
            now=now,
        )
        self._state.pop("open_case", None)
        return self._fire(
            camera,
            frame,
            ctx,
            "Exception evidence casebook ready",
            "A local redacted case package linked Access, Protect, and anonymous visual context for review.",
            {"case_id": open_case["id"], "package": path.name, "access_events": len(open_case["access_events"]), "protect_events": len(open_case["protect_events"]), "max_people": open_case["max_people"]},
        )
