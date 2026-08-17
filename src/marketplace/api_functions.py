"""Declarative UniFi Protect and Access marketplace functions.

The inventory is data, while these two runners own all controller-event parsing,
deduplication, privacy, and control boundaries. No remotely supplied executable
code is imported.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections import Counter, OrderedDict, deque
from pathlib import Path
from typing import Any

from site_time import site_time

from .access import AccessEventFeed, describe, method_of
from .contract import MarketplaceFunction, validate_manifest

API_FUNCTIONS_PATH = Path(__file__).with_name("api_functions.json")
_MAX_INVENTORY_BYTES = 2 * 1024 * 1024
_MAX_SEEN = 4096
_PROFILE_STORE_LOCK = threading.RLock()


class APIFunctionInventoryError(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise APIFunctionInventoryError(f"duplicate JSON member {key!r}")
        result[key] = value
    return result


def load_api_function_manifests(path: str | Path = API_FUNCTIONS_PATH) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        if not source.is_file() or source.stat().st_size > _MAX_INVENTORY_BYTES:
            raise OSError("missing or oversized API-function inventory")
        rows = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                APIFunctionInventoryError(f"non-finite JSON number {value}")
            ),
        )
    except APIFunctionInventoryError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise APIFunctionInventoryError("API-function inventory is invalid") from exc
    if not isinstance(rows, list) or not rows:
        raise APIFunctionInventoryError("API-function inventory must be a non-empty list")
    manifests = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise APIFunctionInventoryError(f"API-function row {index} must be an object")
        errors = validate_manifest(row)
        if errors:
            raise APIFunctionInventoryError(f"{row.get('id', index)}: {'; '.join(errors)}")
        if "api" not in row:
            raise APIFunctionInventoryError(f"{row['id']}: missing api binding")
        if row["id"] in seen:
            raise APIFunctionInventoryError(f"duplicate API-function id {row['id']!r}")
        seen.add(row["id"])
        manifests.append(row)
    return manifests


def _event_seconds(event: dict[str, Any]) -> float:
    raw = event.get("ts") or 0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value <= 0:
        return 0.0
    return value / 1000.0 if value >= 1e11 else value


def _protect_event_id(event: dict[str, Any]) -> str:
    value = event.get("id")
    if value:
        return str(value)[:256]
    projection = {
        "ts": event.get("ts"),
        "camera_id": event.get("camera_id"),
        "type": event.get("type"),
        "smart_types": event.get("smart_types"),
    }
    return hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class ProtectEventFeed:
    """Camera-scoped, bounded, deduplicated view of normalized Protect events."""

    def __init__(
        self,
        event_types=(),
        smart_types=(),
        *,
        max_seen: int = _MAX_SEEN,
        deduplicate: bool = True,
    ):
        self.event_types = frozenset(str(value) for value in event_types)
        self.smart_types = frozenset(str(value).casefold() for value in smart_types)
        self.max_seen = max(16, min(int(max_seen), _MAX_SEEN))
        self.deduplicate = deduplicate is True
        self._seen = OrderedDict()

    def poll(self, ctx, camera_id: str, now: float, window: float) -> list[dict[str, Any]]:
        events = getattr(ctx, "protect_events", None) or ()
        horizon = max(1.0, min(float(window), 86400.0))
        selected = []
        for event in list(events):
            if not isinstance(event, dict):
                continue
            if str(event.get("camera_id") or "") != str(camera_id):
                continue
            event_type = str(event.get("type") or "")
            if self.event_types and event_type not in self.event_types:
                continue
            observed = {str(value).casefold() for value in event.get("smart_types", []) if isinstance(value, str)}
            if self.smart_types and not self.smart_types.intersection(observed):
                continue
            seconds = _event_seconds(event)
            if seconds <= 0 or not -5.0 <= now - seconds <= horizon:
                continue
            identifier = _protect_event_id(event)
            if self.deduplicate and identifier in self._seen:
                continue
            if self.deduplicate:
                self._seen[identifier] = seconds
            selected.append(event)
        while len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        selected.sort(key=lambda event: (_event_seconds(event), _protect_event_id(event)))
        return selected


def _is_closed(ts: float, ctx, configured) -> bool:
    hours = configured if isinstance(configured, (list, tuple)) and len(configured) == 2 else [20, 6]
    try:
        start, end = int(hours[0]), int(hours[1])
        hour = site_time(ts, ctx).hour
    except (TypeError, ValueError, IndexError):
        return False
    if not (0 <= start <= 23 and 0 <= end <= 23):
        return False
    return (hour >= start or hour < end) if start > end else start <= hour < end


class _RuleState:
    def __init__(self):
        self.timestamps: dict[str, deque[float]] = {}
        self.last_digest: dict[str, float] = {}

    def admit(self, key: str, ts: float, mode: str, settings: dict[str, Any]) -> tuple[bool, int]:
        if mode in {"event", "after_hours"}:
            return True, 1
        window = max(5.0, min(float(settings.get("threshold_window_seconds", 300)), 86400.0))
        timestamps = self.timestamps.setdefault(key, deque(maxlen=1024))
        timestamps.append(ts)
        while timestamps and ts - timestamps[0] > window:
            timestamps.popleft()
        if mode == "threshold":
            threshold = max(2, min(int(settings.get("event_threshold", 3)), 1000))
            if len(timestamps) >= threshold:
                count = len(timestamps)
                timestamps.clear()
                return True, count
            return False, len(timestamps)
        interval = max(60.0, min(float(settings.get("digest_seconds", 900)), 86400.0))
        previous = self.last_digest.get(key, 0.0)
        if ts - previous >= interval:
            self.last_digest[key] = ts
            count = len(timestamps)
            timestamps.clear()
            return True, count
        return False, len(timestamps)


class ProtectEventRule(MarketplaceFunction):
    """One declarative read-only rule over the normalized Protect event feed."""

    def __init__(self, settings: dict, *, manifest: dict[str, Any]):
        super().__init__(settings)
        self.manifest = manifest
        binding = manifest["api"]
        self._feed = ProtectEventFeed(
            binding.get("event_types"),
            binding.get("smart_types"),
            deduplicate=manifest["id"] != "protect-event-duplicate-id-audit",
        )
        self._mode = binding.get("mode", "event")
        self._state = _RuleState()
        self._seen_ids: OrderedDict[str, float] = OrderedDict()
        self._last_arrival_seconds = 0.0
        self._last_observed_runtime = 0.0
        self._last_silence_alert = 0.0
        self._watermark_ms = 0
        self._schema_signature: tuple[str, ...] | None = None
        self._event_type_counts: Counter[str] = Counter()
        self._smart_type_counts: Counter[str] = Counter()
        self._scores: deque[float] = deque(maxlen=1024)
        self._event_times: deque[float] = deque(maxlen=1024)
        self._camera_ids: set[str] = set()
        self.name = manifest["id"]

    @staticmethod
    def _safe_projection(event: dict[str, Any]) -> dict[str, Any]:
        smart_types = sorted(
            {str(value).casefold()[:80] for value in event.get("smart_types", []) if isinstance(value, str)}
        )[:16]
        fields = sorted(
            {
                str(value)[:80]
                for value in event.get("source_fields", [])
                if isinstance(value, str) and value
            }
        )[:64]
        return {
            "id": _protect_event_id(event),
            "ts": int(event.get("ts") or 0),
            "camera_id": str(event.get("camera_id") or "")[:128],
            "type": str(event.get("type") or "")[:80],
            "smart_types": smart_types,
            "score": round(float(event.get("score") or 0.0), 3),
            "duration_seconds": round(float(event.get("duration_seconds") or 0.0), 3),
            "start_present": event.get("start_present") is not False,
            "end_present": event.get("end_present") is not False,
            "camera_reference_present": event.get("camera_reference_present") is not False,
            "source_fields": fields,
        }

    @staticmethod
    def _evidence_root(ctx) -> Path | None:
        value = getattr(ctx, "evidence_root", None)
        if value is None:
            return None
        root = Path(value).resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        return root

    def _append_archive(self, ctx, event: dict[str, Any]) -> None:
        root = self._evidence_root(ctx)
        if root is None:
            return
        path = root / "protect-events.jsonl"
        line = json.dumps(
            self._safe_projection(event),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with _PROFILE_STORE_LOCK:
            try:
                existing = path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                existing = []
            payload = "\n".join([item for item in existing if item.strip()][-4095:] + [line]) + "\n"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)

    def _write_watermark(self, ctx) -> None:
        root = self._evidence_root(ctx)
        if root is None:
            return
        path = root / "protect-event-watermark.json"
        payload = json.dumps(
            {"schema": "nexus.protect-watermark/v1", "watermark_ms": self._watermark_ms},
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        with _PROFILE_STORE_LOCK:
            temporary = path.with_suffix(".tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)

    def _profile_observation(self, event: dict[str, Any], ts: float, ctx) -> tuple[bool | None, dict[str, Any]]:
        function_id = self.manifest["id"]
        identifier = _protect_event_id(event)
        seconds = _event_seconds(event)
        duplicate = identifier in self._seen_ids
        self._seen_ids[identifier] = seconds
        self._seen_ids.move_to_end(identifier)
        while len(self._seen_ids) > _MAX_SEEN:
            self._seen_ids.popitem(last=False)

        previous_arrival_seconds = self._last_arrival_seconds
        out_of_order = previous_arrival_seconds > 0 and seconds < previous_arrival_seconds
        self._last_arrival_seconds = seconds
        self._last_observed_runtime = ts
        try:
            event_ms = int(event.get("ts") or 0)
        except (TypeError, ValueError, OverflowError):
            event_ms = 0
        if 0 < event_ms < 100_000_000_000:
            event_ms *= 1000
        self._watermark_ms = max(self._watermark_ms, event_ms)

        source_fields = tuple(self._safe_projection(event)["source_fields"])
        if not source_fields:
            source_fields = ("camera_id", "id", "smart_types", "score", "ts", "type")
        schema_drift = self._schema_signature is not None and source_fields != self._schema_signature
        if self._schema_signature is None:
            self._schema_signature = source_fields

        event_type = str(event.get("type") or "unknown")[:80]
        self._event_type_counts[event_type] += 1
        for smart_type in event.get("smart_types", [])[:16]:
            if isinstance(smart_type, str) and smart_type:
                self._smart_type_counts[smart_type.casefold()[:80]] += 1
        score = event.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)):
            self._scores.append(float(score))
        self._event_times.append(seconds)
        camera_id = str(event.get("camera_id") or "")[:128]
        if camera_id and len(self._camera_ids) < 512:
            self._camera_ids.add(camera_id)

        duration = event.get("duration_seconds")
        duration_seconds = (
            max(0.0, min(float(duration), 86400.0))
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(float(duration))
            else 0.0
        )
        ingest_lag = max(0.0, min(ts - seconds, 86400.0))
        start_present = event.get("start_present") is not False
        end_present = event.get("end_present") is not False
        camera_reference_present = event.get("camera_reference_present") is not False

        if function_id == "protect-event-duplicate-id-audit":
            return duplicate, {"duplicate_event_id": duplicate}
        if function_id == "protect-event-order-anomaly":
            return out_of_order, {"out_of_order": out_of_order, "previous_event_seconds": round(previous_arrival_seconds, 3)}
        if function_id == "protect-event-duration-outlier":
            threshold = max(0.0, min(float(self.settings.get("alert_threshold", 60)), 86400.0))
            return duration_seconds >= threshold, {"duration_seconds": round(duration_seconds, 3), "duration_threshold_seconds": round(threshold, 3)}
        if function_id == "protect-event-start-field-audit":
            return not start_present, {"start_present": start_present}
        if function_id == "protect-event-end-field-audit":
            return not end_present, {"end_present": end_present}
        if function_id == "protect-event-camera-reference-audit":
            return not camera_reference_present, {"camera_reference_present": camera_reference_present}
        if function_id == "protect-event-ingest-lag":
            threshold = max(0.0, min(float(self.settings.get("alert_threshold", 5)), 86400.0))
            return ingest_lag >= threshold, {"ingest_lag_seconds": round(ingest_lag, 3), "lag_threshold_seconds": round(threshold, 3)}
        if function_id == "protect-event-schema-drift":
            return schema_drift, {"schema_drift": schema_drift, "source_fields": list(source_fields)}
        if function_id == "protect-event-type-inventory":
            return None, {"event_type_counts": dict(sorted(self._event_type_counts.items())[:128])}
        if function_id == "protect-event-score-distribution":
            values = list(self._scores)
            return None, {
                "score_count": len(values),
                "score_min": round(min(values), 3) if values else 0.0,
                "score_max": round(max(values), 3) if values else 0.0,
                "score_mean": round(sum(values) / len(values), 3) if values else 0.0,
            }
        if function_id == "protect-event-camera-coverage":
            return None, {"observed_camera_count": len(self._camera_ids)}
        if function_id == "protect-event-hourly-histogram":
            counts = Counter(site_time(value, ctx).tm_hour for value in self._event_times)
            return None, {"hour_counts": {str(key): counts[key] for key in sorted(counts)}}
        if function_id == "protect-event-daily-digest":
            return None, {"event_count": len(self._event_times), "event_type_counts": dict(sorted(self._event_type_counts.items())[:128])}
        if function_id == "protect-smart-detect-subtype-mix":
            return None, {"smart_type_counts": dict(sorted(self._smart_type_counts.items())[:128])}
        if function_id == "protect-motion-smart-ratio":
            smart_count = sum(bool(value) for value in [event.get("smart_types")])
            total = max(1, len(self._event_times))
            return None, {"motion_event_count": total, "motion_events_with_smart_type": smart_count, "smart_ratio": round(smart_count / total, 4)}
        if function_id == "protect-event-jsonl-archive":
            self._append_archive(ctx, event)
            return None, {"archive_recorded": True}
        if function_id == "protect-event-watermark-checkpoint":
            self._write_watermark(ctx)
            return None, {"watermark_ms": self._watermark_ms}
        if function_id in {"protect-event-poll-health", "protect-event-page-saturation", "protect-event-silence-watch"}:
            return False, {}
        return None, {}

    @staticmethod
    def _poll_meta(status: dict[str, Any]) -> dict[str, Any]:
        def count(name: str) -> int:
            value = status.get(name)
            try:
                return max(0, min(int(value or 0), 100_000))
            except (TypeError, ValueError, OverflowError):
                return 0

        latency = status.get("poll_latency_ms")
        try:
            latency_ms = max(0.0, min(float(latency or 0.0), 60_000.0))
        except (TypeError, ValueError, OverflowError):
            latency_ms = 0.0
        return {
            "poll_ok": status.get("ok") is True,
            "poll_latency_ms": round(latency_ms, 3),
            "raw_event_count": count("raw_event_count"),
            "emitted_event_count": count("emitted_event_count"),
            "duplicate_event_count": count("duplicate_event_count"),
            "invalid_event_count": count("invalid_event_count"),
            "page_saturated": status.get("page_saturated") is True,
        }

    def process_poll_health(self, camera, ts: float, ctx, status: dict[str, Any]) -> None:
        meta = self._poll_meta(status)
        function_id = self.manifest["id"]
        emit = (
            function_id == "protect-event-poll-health" and not meta["poll_ok"]
        ) or (
            function_id == "protect-event-page-saturation" and meta["page_saturated"]
        )
        if not emit:
            return
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=function_id,
            title=self.manifest["name"],
            detail="The local Protect event poll produced a bounded health condition for operator review.",
            frame=None,
            meta=meta,
        )

    def tick(self, camera, ts: float, ctx) -> None:
        if self.manifest["id"] != "protect-event-silence-watch":
            return
        if self._last_observed_runtime <= 0:
            self._last_observed_runtime = ts
            return
        threshold = max(5.0, min(float(self.settings.get("threshold_window_seconds", 300)), 86400.0))
        silence = max(0.0, ts - self._last_observed_runtime)
        if silence < threshold or ts - self._last_silence_alert < threshold:
            return
        self._last_silence_alert = ts
        ctx.alerts.fire(
            site=ctx.site,
            camera=camera,
            detector=self.manifest["id"],
            title=self.manifest["name"],
            detail="No normalized Protect events arrived during the configured bounded window.",
            frame=None,
            meta={"silence_seconds": round(silence, 3), "silence_threshold_seconds": round(threshold, 3)},
        )

    def process(self, camera, frame, ts, ctx):
        window = max(5.0, min(float(self.settings.get("event_window_seconds", 300)), 86400.0))
        for event in self._feed.poll(ctx, camera["id"], ts, window):
            if self._mode == "after_hours" and not _is_closed(ts, ctx, self.settings.get("closed_hours")):
                continue
            profile_condition, profile_meta = self._profile_observation(event, ts, ctx)
            if profile_condition is False:
                continue
            admitted, count = self._state.admit(camera["id"], ts, self._mode, self.settings)
            if not admitted:
                continue
            event_type = str(event.get("type") or "event")[:80]
            smart_types = sorted(
                {str(value).casefold()[:80] for value in event.get("smart_types", []) if isinstance(value, str)}
            )[:16]
            score = event.get("score")
            meta = {
                "protect_event_id": _protect_event_id(event),
                "protect_event_type": event_type,
                "smart_types": smart_types,
                "event_seconds": round(_event_seconds(event), 3),
                "matched_event_count": count,
            }
            if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)):
                meta["score"] = round(float(score), 3)
            meta.update(profile_meta)
            ctx.alerts.fire(
                site=ctx.site,
                camera=camera,
                detector=self.manifest["id"],
                title=self.manifest["name"],
                detail=f"UniFi Protect reported {event_type} on {camera['name']}; review the local event record.",
                frame=frame,
                meta=meta,
            )


class AccessEventRule(MarketplaceFunction):
    """One read-only rule over Access developer logs; it never calls unlock."""

    def __init__(self, settings: dict, *, manifest: dict[str, Any]):
        super().__init__(settings)
        self.manifest = manifest
        binding = manifest["api"]
        self._feed = AccessEventFeed(
            self.settings.get("door_id"),
            binding.get("event_kinds") or None,
        )
        self._mode = binding.get("mode", "event")
        self._state = _RuleState()
        self._kind_counts: Counter[str] = Counter()
        self._method_counts: Counter[str] = Counter()
        self._door_hour_counts: Counter[str] = Counter()
        self._first_event_seconds = 0.0
        self._last_event_seconds = 0.0
        self._last_arrival_seconds = 0.0
        self._door_names: dict[str, str] = {}
        self._observed_doors: dict[str, dict[str, Any]] = {}
        self._pending_alarm: dict[str, tuple[str, float]] = {}
        self._pending_doorbell: dict[str, float] = {}
        self.name = manifest["id"]

    def _profile_observation(
        self,
        *,
        seconds: float,
        kind: str,
        event: dict[str, Any],
        record: dict[str, Any],
        ts: float,
        ctx,
    ) -> tuple[bool | None, dict[str, Any]]:
        function_id = self.manifest["id"]
        door_id = str(record.get("door_id") or "unknown")[:128]
        door_name = str(record.get("door_name") or "")[:128]
        method = method_of(event)
        previous_arrival = self._last_arrival_seconds
        out_of_order = previous_arrival > 0 and seconds < previous_arrival
        self._last_arrival_seconds = seconds
        delivery_lag = max(0.0, min(ts - seconds, 86400.0))

        previous_name = self._door_names.get(door_id, "")
        name_drift = bool(previous_name and door_name and previous_name != door_name)
        if door_name:
            self._door_names[door_id] = door_name

        self._kind_counts[kind] += 1
        self._method_counts[method] += 1
        self._first_event_seconds = seconds if self._first_event_seconds <= 0 else min(self._first_event_seconds, seconds)
        self._last_event_seconds = max(self._last_event_seconds, seconds)
        hour = site_time(seconds, ctx).tm_hour
        self._door_hour_counts[f"{door_id}:{hour:02d}"] += 1
        roster = self._observed_doors.setdefault(
            door_id,
            {"door_name": door_name, "first_event_seconds": seconds, "last_event_seconds": seconds},
        )
        roster["door_name"] = door_name or roster["door_name"]
        roster["first_event_seconds"] = min(float(roster["first_event_seconds"]), seconds)
        roster["last_event_seconds"] = max(float(roster["last_event_seconds"]), seconds)
        if len(self._observed_doors) > 512:
            oldest = min(
                self._observed_doors,
                key=lambda key: float(self._observed_doors[key]["last_event_seconds"]),
            )
            self._observed_doors.pop(oldest, None)

        pending_alarm = self._pending_alarm.get(door_id)
        alarm_duration = None
        if kind in {"forced_open", "held_open"}:
            self._pending_alarm[door_id] = (kind, seconds)
        elif kind == "door_closed" and pending_alarm is not None:
            alarm_duration = max(0.0, seconds - pending_alarm[1])
            self._pending_alarm.pop(door_id, None)

        pending_doorbell = self._pending_doorbell.get(door_id)
        doorbell_next = None
        if kind == "doorbell":
            self._pending_doorbell[door_id] = seconds
        elif pending_doorbell is not None:
            doorbell_next = max(0.0, seconds - pending_doorbell)
            self._pending_doorbell.pop(door_id, None)

        if function_id == "access-event-type-census":
            return None, {"event_kind_counts": dict(sorted(self._kind_counts.items()))}
        if function_id == "access-grant-denial-ratio":
            granted = self._kind_counts.get("granted", 0)
            denied = self._kind_counts.get("denied", 0)
            total = granted + denied
            return None, {
                "grant_count": granted,
                "denied_count": denied,
                "grant_ratio": round(granted / total, 4) if total else 0.0,
            }
        if function_id == "access-credential-method-mix":
            return None, {"method_counts": dict(sorted(self._method_counts.items()))}
        if function_id == "access-first-last-door-event":
            return None, {
                "first_event_seconds": round(self._first_event_seconds, 3),
                "last_event_seconds": round(self._last_event_seconds, 3),
            }
        if function_id == "access-door-activity-heatmap":
            return None, {"door_hour_counts": dict(sorted(self._door_hour_counts.items()))}
        if function_id == "access-doorbell-volume-summary":
            return None, {"doorbell_count": self._kind_counts.get("doorbell", 0)}
        if function_id == "access-observed-door-roster":
            return None, {"observed_doors": dict(sorted(self._observed_doors.items()))}
        if function_id == "access-door-name-drift":
            return name_drift, {
                "door_id": door_id,
                "previous_door_name": previous_name,
                "door_name": door_name,
                "door_name_drift": name_drift,
            }
        if function_id == "access-log-delivery-lag":
            threshold = max(0.0, min(float(self.settings.get("alert_threshold", 5)), 86400.0))
            return delivery_lag >= threshold, {
                "delivery_lag_seconds": round(delivery_lag, 3),
                "lag_threshold_seconds": round(threshold, 3),
            }
        if function_id == "access-out-of-order-event-review":
            return out_of_order, {
                "out_of_order": out_of_order,
                "previous_event_seconds": round(previous_arrival, 3),
            }
        if function_id == "access-unclassified-event-review":
            return kind == "other", {"kind": kind}
        if function_id == "access-unreported-method-review":
            return method == "unknown", {"method": method}
        if function_id in {"access-door-alarm-duration-ledger", "access-close-confirmation-gap"}:
            if alarm_duration is None:
                return False, {}
            key = (
                "alarm_duration_seconds"
                if function_id == "access-door-alarm-duration-ledger"
                else "close_confirmation_gap_seconds"
            )
            return True, {key: round(alarm_duration, 3), "alarm_kind": pending_alarm[0] if pending_alarm else "unknown"}
        if function_id == "access-doorbell-next-event-timing":
            if doorbell_next is None:
                return False, {}
            return True, {"doorbell_next_event_seconds": round(doorbell_next, 3), "next_event_kind": kind}
        if function_id == "access-remote-unlock-ledger":
            return None, {"remote_unlock_count": self._kind_counts.get("unlock_command", 0)}
        return None, {}

    def process(self, camera, frame, ts, ctx):
        window = max(5.0, min(float(self.settings.get("event_window_seconds", 300)), 86400.0))
        for seconds, kind, event in self._feed.poll(ctx, ts, window):
            if self._mode == "after_hours" and not _is_closed(ts, ctx, self.settings.get("closed_hours")):
                continue
            door_key = str(event.get("door_id") or self.settings.get("door_id") or "all")
            record = describe(event, include_actor=False)
            profile_condition, profile_meta = self._profile_observation(
                seconds=seconds,
                kind=kind,
                event=event,
                record=record,
                ts=ts,
                ctx=ctx,
            )
            if profile_condition is False:
                continue
            if profile_condition is True:
                admitted, count = True, 1
            else:
                admitted, count = self._state.admit(door_key, ts, self._mode, self.settings)
            if not admitted:
                continue
            record["matched_event_count"] = count
            record.update(profile_meta)
            ctx.alerts.fire(
                site=ctx.site,
                camera=camera,
                detector=self.manifest["id"],
                title=self.manifest["name"],
                detail=(
                    f"UniFi Access reported {kind.replace('_', ' ')} at "
                    f"{record['door_name'] or record['door_id'] or 'the configured door'}; review the local event record."
                ),
                frame=frame,
                meta=record,
            )


def function_class_for(manifest: dict[str, Any]):
    """Create a local class around a signed-image runner; inventory is data only."""
    surface = manifest["api"]["surface"]
    base = ProtectEventRule if surface == "protect" else AccessEventRule

    class Function(base):
        def __init__(self, settings):
            super().__init__(settings, manifest=manifest)

    Function.__name__ = f"APIFunction_{manifest['id'].replace('-', '_')}"
    Function.__qualname__ = Function.__name__
    Function.name = manifest["id"]
    Function.api_function = True
    Function.api_manifest = manifest
    return Function
