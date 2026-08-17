"""Shared lifecycle for declarative UniFi Protect and Access functions."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .api_functions import AccessEventRule, ProtectEventRule

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_CLIP_DURATION_MS = 300_000
_MAX_CLIP_BYTES = 500 * 1024 * 1024
_DEFAULT_SNAPSHOT_RETENTION_DAYS = 30
_DEFAULT_SNAPSHOT_MAX_FILES = 5_000
_DEFAULT_SNAPSHOT_STORAGE_QUOTA_BYTES = 5 * 1024 * 1024 * 1024


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        value = default
    return max(minimum, min(value, maximum))


class APIRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class _Binding:
    function_id: str
    manifest: dict[str, Any]
    camera: dict[str, Any]
    settings: dict[str, Any]
    rule: Any = None
    last_sample_at: float = 0.0
    last_inventory: dict[str, Any] | None = None
    last_frame_at: float = 0.0
    last_frame_hash: str = ""
    duplicate_streak: int = 0
    last_metrics: dict[str, float] | None = None
    frame_count: int = 0
    decode_errors: int = 0
    stream_status_count: int = 0
    reconnect_count: int = 0
    last_schedule_day: str = ""


class APIFunctionRuntime:
    """Compile all API functions once and route shared source data to them."""

    def __init__(
        self,
        config: dict[str, Any],
        registry: dict[str, dict[str, Any]],
        *,
        alerts,
        site: str,
        evidence_root: str | Path,
        protect_client=None,
        access_control=None,
        clock: Callable[[], float],
    ):
        self.alerts = alerts
        self.site = site
        self.protect_client = protect_client
        self.access_control = access_control
        self.clock = clock
        self._started_at = float(clock())
        self.evidence_root = Path(evidence_root).resolve()
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.evidence_root, 0o700)
        self._lock = threading.RLock()
        self._evidence_lock = threading.Lock()
        self._bindings: list[_Binding] = []
        self._failures: dict[str, str] = {}
        self._request_ids = set()
        self._snapshot_request_ids: set[str] = set()
        self._latest_snapshot_payloads: dict[str, tuple[float, bytes]] = {}
        self._snapshot_suppressed: dict[str, int] = {}
        self._snapshot_retention_days = _bounded_env_int(
            "VISION_SNAPSHOT_RETENTION_DAYS",
            _DEFAULT_SNAPSHOT_RETENTION_DAYS,
            1,
            3650,
        )
        self._snapshot_max_files = _bounded_env_int(
            "VISION_SNAPSHOT_MAX_FILES",
            _DEFAULT_SNAPSHOT_MAX_FILES,
            1,
            50_000,
        )
        self._snapshot_storage_quota_bytes = _bounded_env_int(
            "VISION_SNAPSHOT_STORAGE_QUOTA_BYTES",
            _DEFAULT_SNAPSHOT_STORAGE_QUOTA_BYTES,
            1024,
            50 * 1024 * 1024 * 1024,
        )
        self._audit_path = self.evidence_root / "access-control-audit.jsonl"
        self._clip_index_path = self.evidence_root / "clip-export-index.jsonl"
        self._inventory_snapshot: dict[str, dict[str, Any]] = {}
        self._timezone = self._timezone_from(config)
        self._compile(config, registry)
        self._load_request_ids()

    @staticmethod
    def _timezone_from(config: dict[str, Any]):
        name = str((config.get("site") or {}).get("timezone") or "UTC")
        try:
            return ZoneInfo(name)
        except Exception:
            return ZoneInfo("UTC")

    def _compile(self, config, registry) -> None:
        global_settings = config.get("detector_settings") or {}
        for camera in config.get("cameras") or []:
            if not isinstance(camera, dict):
                continue
            for function_id in camera.get("detectors") or []:
                entry = registry.get(function_id)
                manifest = (entry or {}).get("manifest")
                if not isinstance(manifest, dict) or not isinstance(manifest.get("api"), dict):
                    continue
                settings = dict(global_settings.get(function_id) or {})
                settings.update(camera.get(function_id) or {})
                runner = manifest["api"]["runner"]
                rule = None
                if runner == "protect_event":
                    rule = ProtectEventRule(settings, manifest=manifest)
                elif runner == "access_event":
                    rule = AccessEventRule(settings, manifest=manifest)
                self._bindings.append(
                    _Binding(
                        function_id=function_id,
                        manifest=manifest,
                        camera=dict(camera),
                        settings=settings,
                        rule=rule,
                    )
                )
        keys = [(binding.function_id, binding.camera.get("id")) for binding in self._bindings]
        if len(keys) != len(set(keys)):
            raise APIRuntimeError("duplicate_binding", "API function is configured more than once per camera")

    def _context(self, *, protect_events=(), access_events=()):
        return SimpleNamespace(
            site=self.site,
            timezone=self._timezone,
            alerts=self.alerts,
            evidence_root=self.evidence_root,
            protect_events=list(protect_events),
            access_events=list(access_events),
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            surfaces = {"protect": 0, "access": 0}
            for binding in self._bindings:
                surfaces[binding.manifest["api"]["surface"]] += 1
            return {
                "binding_count": len(self._bindings),
                "protect_bindings": surfaces["protect"],
                "access_bindings": surfaces["access"],
                "failed_bindings": len(self._failures),
            }

    def configured_ids(self) -> set[str]:
        return {binding.function_id for binding in self._bindings}

    def attach_adapters(self, *, protect_client=None, access_control=None) -> None:
        """Attach already-authorized local controller adapters."""
        with self._lock:
            if protect_client is not None:
                self.protect_client = protect_client
            if access_control is not None:
                self.access_control = access_control

    def _dispatch(self, source: str, event: dict[str, Any]) -> None:
        now = float(self.clock())
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            runner = binding.manifest["api"]["runner"]
            if source == "protect" and runner == "protect_event":
                if str(event.get("camera_id") or "") != str(binding.camera.get("id") or ""):
                    continue
                context = self._context(protect_events=[event])
            elif source == "access" and runner == "access_event":
                context = self._context(access_events=[event])
            else:
                continue
            try:
                binding.rule.process(binding.camera, None, now, context)
                self._failures.pop(binding.function_id, None)
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__

    def on_protect_event(self, event: dict[str, Any]) -> None:
        if isinstance(event, dict):
            self._dispatch("protect", event)
            self._handle_event_clips(event)

    def _handle_event_clips(self, event: dict[str, Any]) -> None:
        camera_id = str(event.get("camera_id") or "")
        try:
            event_ms = int(event.get("ts") or 0)
        except (TypeError, ValueError, OverflowError):
            return
        if not camera_id or event_ms <= 0:
            return
        event_type = str(event.get("type") or "").casefold()
        smart_types = event.get("smart_types")
        has_smart = isinstance(smart_types, list) and bool(smart_types)
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            api = binding.manifest["api"]
            if api["runner"] != "protect_evidence" or api["profile"] != "event_clip":
                continue
            if str(binding.camera.get("id") or "") != camera_id:
                continue
            if binding.function_id == "motion-event-clip-export" and "motion" not in event_type:
                continue
            if binding.function_id == "smart-event-clip-export" and not (has_smart or "smart" in event_type):
                continue
            pre_seconds = max(0.0, min(float(binding.settings.get("pre_seconds", 5)), 120.0))
            post_seconds = max(0.1, min(float(binding.settings.get("post_seconds", 10)), 180.0))
            start_ms = max(1, event_ms - int(pre_seconds * 1000))
            end_ms = event_ms + int(post_seconds * 1000)
            try:
                result = self._export_clip_binding(binding, camera_id, start_ms, end_ms)
                meta = dict(result)
                meta.update(
                    {
                        "event_id": str(event.get("id") or "")[:256],
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                    }
                )
                self._fire(
                    binding,
                    binding.manifest["name"],
                    f"A bounded local Protect clip was exported for {binding.camera.get('name', 'the configured camera')}.",
                    meta,
                )
                self._failures.pop(binding.function_id, None)
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__

    def on_protect_poll(self, status: dict[str, Any]) -> None:
        if not isinstance(status, dict):
            return
        now = float(self.clock())
        context = self._context()
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_event":
                continue
            try:
                binding.rule.process_poll_health(binding.camera, now, context, status)
                self._failures.pop(binding.function_id, None)
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__
        self.tick(now)

    def tick(self, ts: float | None = None) -> None:
        now = float(self.clock() if ts is None else ts)
        context = self._context()
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_event":
                continue
            try:
                binding.rule.tick(binding.camera, now, context)
                self._failures.pop(binding.function_id, None)
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__

    def on_access_event(self, event: dict[str, Any]) -> None:
        if isinstance(event, dict):
            self._dispatch("access", event)

    def _fire(self, binding: _Binding, title: str, detail: str, meta: dict[str, Any], frame=None) -> None:
        self.alerts.fire(
            site=self.site,
            camera=binding.camera,
            detector=binding.function_id,
            title=title,
            detail=detail,
            frame=frame,
            meta=meta,
        )

    @staticmethod
    def _safe_inventory_camera(camera: dict[str, Any]) -> dict[str, Any] | None:
        identifier = str(camera.get("id") or "").strip()[:128]
        if not identifier:
            return None
        raw_stream = camera.get("stream")
        stream: dict[str, Any] = raw_stream if isinstance(raw_stream, dict) else {}

        def dimension(name: str) -> int:
            try:
                return max(0, min(int(stream.get(name) or 0), 100_000))
            except (TypeError, ValueError, OverflowError):
                return 0

        return {
            "id": identifier,
            "name": str(camera.get("name") or "").strip()[:128],
            "model": str(camera.get("model") or "unknown").strip()[:128] or "unknown",
            "state": str(camera.get("state") or "UNKNOWN").strip().upper()[:40],
            "rtsp_enabled": camera.get("rtsp_enabled") is True,
            "stream": {
                "width": dimension("width"),
                "height": dimension("height"),
                "fps": dimension("fps"),
            },
        }

    def on_inventory(
        self,
        cameras: list[dict[str, Any]],
        ts: float | None = None,
        *,
        api_latency_ms: float | None = None,
    ) -> None:
        observed_at = float(self.clock() if ts is None else ts)
        sanitized = []
        for raw in list(cameras or [])[:512]:
            if isinstance(raw, dict) and (camera := self._safe_inventory_camera(raw)) is not None:
                sanitized.append(camera)
        by_id = {camera["id"]: camera for camera in sanitized}
        names = [camera["name"] for camera in sanitized]
        duplicates = {name for name in names if name and names.count(name) > 1}
        previous_snapshot = self._inventory_snapshot
        current_ids = set(by_id)
        previous_ids = set(previous_snapshot)
        added_ids = sorted(current_ids - previous_ids)[:512]
        removed_ids = sorted(previous_ids - current_ids)[:512]
        model_counts: dict[str, int] = {}
        for camera in sanitized:
            model_counts[camera["model"]] = model_counts.get(camera["model"], 0) + 1
        model_counts = dict(sorted(model_counts.items())[:128])
        connected_count = sum(camera["state"] == "CONNECTED" for camera in sanitized)
        latency = None
        if isinstance(api_latency_ms, (int, float)) and not isinstance(api_latency_ms, bool):
            candidate = float(api_latency_ms)
            if math.isfinite(candidate):
                latency = round(max(0.0, min(candidate, 60_000.0)), 3)
        with self._lock:
            bindings = tuple(self._bindings)
        emitted_global: set[str] = set()
        global_functions = {
            "protect-camera-api-latency",
            "protect-camera-count-trend",
            "protect-camera-discovery-delta",
            "protect-camera-discovery-failure-log",
            "protect-camera-fleet-inventory",
            "protect-camera-model-mix",
        }
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_inventory":
                continue
            if binding.function_id in global_functions and binding.function_id in emitted_global:
                continue
            camera = by_id.get(str(binding.camera.get("id") or ""))
            function_id = binding.function_id
            emit = False
            meta: dict[str, Any] = {
                "observed_at": round(observed_at, 3),
                "camera_present": camera is not None,
                "state": str((camera or {}).get("state") or "unknown")[:40],
                "rtsp_enabled": (camera or {}).get("rtsp_enabled") is True,
            }
            if function_id == "protect-camera-offline-watch":
                emit = camera is None or str((camera or {}).get("state") or "").upper() != "CONNECTED"
            elif function_id == "protect-rtsp-enable-audit":
                emit = camera is None or (camera or {}).get("rtsp_enabled") is not True
            elif function_id == "protect-camera-unnamed-records":
                emit = camera is None or not str((camera or {}).get("name") or "").strip()
            elif function_id == "protect-camera-name-collision-audit":
                emit = bool(camera and camera.get("name") in duplicates)
                meta["duplicate_name"] = str((camera or {}).get("name") or "")[:128]
            elif function_id == "protect-camera-api-latency":
                emit = latency is not None
                meta["api_latency_ms"] = latency
            elif function_id == "protect-camera-count-trend":
                emit = bool(previous_snapshot)
                meta.update(
                    {
                        "camera_count": len(sanitized),
                        "previous_camera_count": len(previous_snapshot),
                        "camera_count_delta": len(sanitized) - len(previous_snapshot),
                    }
                )
            elif function_id == "protect-camera-discovery-delta":
                emit = bool(previous_snapshot) and bool(added_ids or removed_ids)
                meta.update({"added_camera_ids": added_ids, "removed_camera_ids": removed_ids})
            elif function_id == "protect-camera-discovery-failure-log":
                emit = not sanitized
                meta["camera_count"] = len(sanitized)
            elif function_id == "protect-camera-fleet-inventory":
                emit = not previous_snapshot or previous_snapshot != by_id
                meta.update(
                    {
                        "camera_count": len(sanitized),
                        "connected_count": connected_count,
                        "offline_count": len(sanitized) - connected_count,
                        "rtsp_enabled_count": sum(camera["rtsp_enabled"] for camera in sanitized),
                    }
                )
            elif function_id == "protect-camera-model-mix":
                previous_models: dict[str, int] = {}
                for old in previous_snapshot.values():
                    model = str(old.get("model") or "unknown")
                    previous_models[model] = previous_models.get(model, 0) + 1
                emit = not previous_snapshot or dict(sorted(previous_models.items())) != model_counts
                meta["model_counts"] = model_counts
            elif function_id == "protect-camera-state-flap-log":
                previous = binding.last_inventory
                emit = previous is not None and (previous or {}).get("state") != (camera or {}).get("state")
                meta["previous_state"] = str((previous or {}).get("state") or "unknown")[:40]
            elif function_id == "protect-rtsp-availability-delta":
                previous = binding.last_inventory
                emit = previous is not None and (previous or {}).get("rtsp_enabled") != (camera or {}).get("rtsp_enabled")
                meta["previous_rtsp_enabled"] = (previous or {}).get("rtsp_enabled") is True
            elif function_id == "protect-stream-profile-drift":
                previous = binding.last_inventory
                emit = previous is not None and (previous or {}).get("stream") != (camera or {}).get("stream")
                meta.update(
                    {
                        "previous_stream": dict((previous or {}).get("stream") or {}),
                        "stream": dict((camera or {}).get("stream") or {}),
                    }
                )
            elif function_id == "protect-stream-fps-register":
                previous = binding.last_inventory
                old_fps = ((previous or {}).get("stream") or {}).get("fps")
                fps = ((camera or {}).get("stream") or {}).get("fps")
                emit = previous is None or old_fps != fps
                meta.update({"fps": fps or 0, "previous_fps": old_fps or 0})
            elif function_id == "protect-stream-resolution-register":
                previous = binding.last_inventory
                old_stream = (previous or {}).get("stream") or {}
                stream = (camera or {}).get("stream") or {}
                old_resolution = [old_stream.get("width", 0), old_stream.get("height", 0)]
                resolution = [stream.get("width", 0), stream.get("height", 0)]
                emit = previous is None or old_resolution != resolution
                meta.update({"resolution": resolution, "previous_resolution": old_resolution})
            else:
                emit = binding.last_inventory is None
            binding.last_inventory = dict(camera or {})
            if emit:
                emitted_global.add(function_id)
                self._fire(
                    binding,
                    binding.manifest["name"],
                    f"Protect camera inventory produced a review condition for {binding.camera.get('name', 'the configured camera')}.",
                    meta,
                )
        self._inventory_snapshot = {identifier: dict(camera) for identifier, camera in by_id.items()}

    @staticmethod
    def _frame_metrics(frame) -> dict[str, float]:
        import numpy as np

        if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            raise ValueError("invalid frame")
        height, width = frame.shape[:2]
        y_step = max(1, height // 90)
        x_step = max(1, width // 160)
        sample = np.asarray(frame[::y_step, ::x_step][:90, :160], dtype=np.float32)
        if sample.ndim == 2:
            gray = sample
            channel_spread = 0.0
            channel_means = [float(np.mean(sample))] * 3
        elif sample.ndim == 3 and sample.shape[2] >= 3:
            # Stream frames use OpenCV's BGR convention.
            channels = sample[:, :, :3]
            gray = channels[:, :, 0] * 0.114 + channels[:, :, 1] * 0.587 + channels[:, :, 2] * 0.299
            channel_spread = float(np.mean(np.max(channels, axis=2) - np.min(channels, axis=2)))
            channel_means = [float(np.mean(channels[:, :, index])) for index in range(3)]
        else:
            raise ValueError("invalid frame channels")
        mean = float(np.mean(gray))
        std = float(np.std(gray))
        black_ratio = float(np.mean(gray <= 8))
        white_ratio = float(np.mean(gray >= 247))
        horizontal = np.diff(gray, axis=1)
        vertical = np.diff(gray, axis=0)
        blur = float(np.var(horizontal) + np.var(vertical))
        sample_height, sample_width = gray.shape[:2]
        border_y = max(1, sample_height // 8)
        border_x = max(1, sample_width // 8)
        center = gray[border_y : sample_height - border_y, border_x : sample_width - border_x]
        corners = np.concatenate(
            [
                gray[:border_y, :border_x].reshape(-1),
                gray[:border_y, -border_x:].reshape(-1),
                gray[-border_y:, :border_x].reshape(-1),
                gray[-border_y:, -border_x:].reshape(-1),
            ]
        )
        center_mean = float(np.mean(center)) if center.size else mean
        corner_mean = float(np.mean(corners)) if corners.size else mean
        edge_black_ratio = max(
            float(np.mean(gray[:border_y] <= 8)),
            float(np.mean(gray[-border_y:] <= 8)),
            float(np.mean(gray[:, :border_x] <= 8)),
            float(np.mean(gray[:, -border_x:] <= 8)),
        )
        noise = float(np.mean(np.abs(horizontal))) + float(np.mean(np.abs(vertical)))
        boundary_values = []
        if sample_width > 8:
            after = gray[:, 8::8]
            before = gray[:, 7::8][:, : after.shape[1]]
            boundary_values.append(float(np.mean(np.abs(after - before))))
        if sample_height > 8:
            after = gray[8::8]
            before = gray[7::8][: after.shape[0]]
            boundary_values.append(float(np.mean(np.abs(after - before))))
        blockiness = sum(boundary_values) / len(boundary_values) if boundary_values else 0.0
        row_stuck_ratio = float(np.mean(np.std(gray, axis=1) <= 0.5))
        column_stuck_ratio = float(np.mean(np.std(gray, axis=0) <= 0.5))
        extreme_ratio = float(np.mean((gray <= 1) | (gray >= 254)))
        quality_score = max(
            0.0,
            min(
                100.0,
                100.0
                - black_ratio * 45.0
                - white_ratio * 45.0
                - max(0.0, 15.0 - std) * 2.0
                - min(channel_spread, 80.0) * 0.1,
            ),
        )
        return {
            "luminance": mean,
            "contrast": std,
            "black_ratio": black_ratio,
            "white_ratio": white_ratio,
            "blur_variance": blur,
            "channel_spread": channel_spread,
            "blue_mean": channel_means[0],
            "green_mean": channel_means[1],
            "red_mean": channel_means[2],
            "color_cast": max(channel_means) - min(channel_means),
            "noise_estimate": noise,
            "blockiness_estimate": blockiness,
            "corner_vignetting": max(0.0, center_mean - corner_mean),
            "letterbox_edge_black_ratio": edge_black_ratio,
            "stuck_row_ratio": row_stuck_ratio,
            "stuck_column_ratio": column_stuck_ratio,
            "extreme_pixel_ratio": extreme_ratio,
            "quality_score": quality_score,
            "width": float(width),
            "height": float(height),
            "aspect_ratio": float(width) / max(1.0, float(height)),
            "frame_bytes": float(np.asarray(frame).nbytes),
        }

    @staticmethod
    def _stream_condition(function_id: str, metrics: dict[str, float], settings: dict[str, Any]) -> bool:
        if function_id == "rtsp-black-frame-rate":
            return metrics["black_ratio"] >= 0.95
        if function_id == "rtsp-overexposed-frame-rate":
            return metrics["white_ratio"] >= 0.95
        if function_id == "rtsp-low-contrast-watch":
            return metrics["contrast"] <= 12.0
        if function_id in {"rtsp-blur-score", "rtsp-focus-zone-sharpness"}:
            return metrics["blur_variance"] <= 50.0
        if function_id == "rtsp-grayscale-channel-audit":
            return metrics["channel_spread"] <= 2.0
        if function_id == "rtsp-aspect-ratio-drift":
            return metrics.get("aspect_ratio_changed", 0.0) == 1.0
        if function_id == "rtsp-frame-hash-duplication":
            return metrics.get("duplicate_frame", 0.0) == 1.0
        if function_id == "rtsp-effective-fps":
            return metrics.get("frame_gap_seconds", 0.0) > 0.0
        if function_id == "rtsp-frame-gap-watch":
            threshold = max(0.1, min(float(settings.get("alert_threshold", 5)), 86400.0))
            return metrics.get("frame_gap_seconds", 0.0) >= threshold
        if function_id in {"rtsp-frame-size-consistency", "rtsp-resolution-drift"}:
            key = "frame_size_changed" if function_id == "rtsp-frame-size-consistency" else "resolution_changed"
            return metrics.get(key, 0.0) == 1.0
        if function_id == "rtsp-freeze-watch":
            threshold = max(2, min(int(settings.get("event_threshold", 3)), 1000))
            return metrics.get("duplicate_streak", 0.0) >= threshold
        if function_id == "rtsp-luminance-flicker":
            threshold = max(0.1, min(float(settings.get("alert_threshold", 20)), 255.0))
            return metrics.get("luminance_delta", 0.0) >= threshold
        if function_id == "rtsp-color-flicker":
            threshold = max(0.1, min(float(settings.get("alert_threshold", 20)), 255.0))
            return metrics.get("color_delta", 0.0) >= threshold
        if function_id == "rtsp-color-cast-watch":
            threshold = max(1.0, min(float(settings.get("alert_threshold", 35)), 255.0))
            return metrics["color_cast"] >= threshold
        if function_id == "rtsp-blockiness-estimate":
            threshold = max(1.0, min(float(settings.get("alert_threshold", 20)), 255.0))
            return metrics["blockiness_estimate"] >= threshold
        if function_id == "rtsp-dark-corner-vignetting":
            threshold = max(1.0, min(float(settings.get("alert_threshold", 30)), 255.0))
            return metrics["corner_vignetting"] >= threshold
        if function_id == "rtsp-noise-estimate":
            threshold = max(1.0, min(float(settings.get("alert_threshold", 25)), 510.0))
            return metrics["noise_estimate"] >= threshold
        if function_id == "rtsp-letterbox-detection":
            return metrics["letterbox_edge_black_ratio"] >= 0.8
        if function_id == "rtsp-dead-pixel-cluster-watch":
            return metrics["extreme_pixel_ratio"] >= 0.01 and metrics["contrast"] > 2.0
        if function_id == "rtsp-stuck-row-column-watch":
            return max(metrics["stuck_row_ratio"], metrics["stuck_column_ratio"]) >= 0.1
        if function_id == "rtsp-startup-latency":
            return metrics.get("first_sample", 0.0) == 1.0
        if function_id in {"rtsp-decode-error-rate", "rtsp-reconnect-rate"}:
            return False
        if function_id in {"rtsp-connectivity-probe", "rtsp-rolling-quality-digest"}:
            return True
        return True

    def _scheduled_snapshot_due(self, binding: _Binding, ts: float) -> tuple[bool, str]:
        defaults = {
            "opening-time-snapshot": "08:00",
            "closing-time-snapshot": "17:00",
            "scheduled-reference-snapshot": "12:00",
        }
        default_time = defaults.get(binding.function_id)
        if default_time is None:
            return False, ""
        local_time = str(binding.settings.get("local_time") or default_time)
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", local_time)
        if match is None:
            raise ValueError("snapshot local_time must be HH:MM")
        local = datetime.fromtimestamp(ts, self._timezone)
        target_seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60
        observed_seconds = local.hour * 3600 + local.minute * 60 + local.second
        window = max(1, min(int(binding.settings.get("schedule_window_seconds", 90)), 3600))
        day = local.date().isoformat()
        return 0 <= observed_seconds - target_seconds <= window and binding.last_schedule_day != day, day

    @staticmethod
    def _encode_snapshot_payload(frame) -> bytes:
        import io
        import numpy as np
        from PIL import Image

        array = np.asarray(frame)
        if array.ndim == 3 and array.shape[2] >= 3:
            array = array[:, :, :3][:, :, ::-1]
        image = Image.fromarray(array.astype("uint8"))
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG", quality=85, optimize=True)
        return encoded.getvalue()

    def _prune_snapshots(self, directory: Path, *, now: float, incoming_bytes: int) -> int:
        cutoff = now - self._snapshot_retention_days * 86400
        entries: list[tuple[Path, float, int]] = []
        for path in directory.glob("*.jpg"):
            try:
                if path.is_file():
                    stat_result = path.stat()
                    entries.append((path, stat_result.st_mtime, stat_result.st_size))
            except FileNotFoundError:
                continue
        entries.sort(key=lambda item: (item[1], item[0].name))
        survivors: list[tuple[Path, float, int]] = []
        pruned = 0
        for entry in entries:
            if entry[1] < cutoff:
                entry[0].unlink(missing_ok=True)
                pruned += 1
            else:
                survivors.append(entry)
        storage = sum(entry[2] for entry in survivors)
        while survivors and (
            len(survivors) >= self._snapshot_max_files
            or storage + incoming_bytes > self._snapshot_storage_quota_bytes
        ):
            path, _mtime, size = survivors.pop(0)
            path.unlink(missing_ok=True)
            storage -= size
            pruned += 1
        if (
            incoming_bytes > self._snapshot_storage_quota_bytes
            or len(survivors) >= self._snapshot_max_files
            or storage + incoming_bytes > self._snapshot_storage_quota_bytes
        ):
            raise ValueError("snapshot storage quota would be exceeded")
        return pruned

    def _store_snapshot_payload(
        self,
        binding: _Binding,
        payload: bytes,
        ts: float,
        *,
        trigger: str,
    ) -> dict[str, Any]:
        directory = self.evidence_root / "snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        maximum = max(1024, min(int(binding.settings.get("max_snapshot_bytes", 10 * 1024 * 1024)), 25 * 1024 * 1024))
        if len(payload) > maximum:
            raise ValueError("snapshot exceeds configured byte limit")
        captured_at = float(ts)
        if not math.isfinite(captured_at) or captured_at < 0:
            raise ValueError("snapshot timestamp is invalid")
        digest = hashlib.sha256(payload).hexdigest()
        camera_id = re.sub(r"[^A-Za-z0-9_-]", "-", str(binding.camera.get("id") or "camera"))[:64]
        function_id = re.sub(r"[^A-Za-z0-9_-]", "-", binding.function_id)[:80]
        timestamp_ms = int(captured_at * 1000)
        path = directory / f"{camera_id}__{function_id}__{timestamp_ms}__{digest[:16]}.jpg"
        partial = Path(str(path) + ".partial")
        with self._evidence_lock:
            pruned = self._prune_snapshots(
                directory,
                now=float(self.clock()),
                incoming_bytes=len(payload),
            )
            partial.unlink(missing_ok=True)
            descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("snapshot write made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            except Exception:
                partial.unlink(missing_ok=True)
                raise
            finally:
                os.close(descriptor)
            os.replace(partial, path)
            os.chmod(path, 0o600)
            os.utime(path, (captured_at, captured_at))
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            files = [candidate for candidate in directory.glob("*.jpg") if candidate.is_file()]
            storage = sum(candidate.stat().st_size for candidate in files)
        return {
            "snapshot_sha256": digest,
            "snapshot_bytes": len(payload),
            "snapshot_path": path.relative_to(self.evidence_root).as_posix(),
            "trigger": trigger,
            "pruned_count": pruned,
            "snapshot_count": len(files),
            "snapshot_storage_bytes": storage,
            "snapshot_storage_quota_bytes": self._snapshot_storage_quota_bytes,
        }

    def _capture_snapshot(
        self,
        binding: _Binding,
        frame,
        ts: float,
        *,
        trigger: str,
    ) -> dict[str, Any] | None:
        if binding.camera.get("privacy_mode") == "skeleton":
            return None
        payload = self._encode_snapshot_payload(frame)
        return self._store_snapshot_payload(binding, payload, ts, trigger=trigger)

    def _capture_zone_snapshot(self, binding: _Binding, frame, ts: float) -> dict[str, Any] | None:
        if binding.camera.get("privacy_mode") == "skeleton":
            return None
        import numpy as np

        crop_box = binding.settings.get("crop_box")
        if not isinstance(crop_box, (list, tuple)) or len(crop_box) != 4:
            raise ValueError("snapshot crop_box must contain four normalized coordinates")
        try:
            x1, y1, x2, y2 = (float(value) for value in crop_box)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("snapshot crop_box coordinates must be finite numbers") from None
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            raise ValueError("snapshot crop_box coordinates must be finite numbers")
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            raise ValueError("snapshot crop_box must be within normalized frame bounds")
        array = np.asarray(frame)
        height, width = int(array.shape[0]), int(array.shape[1])
        left = max(0, min(width - 1, int(round(x1 * width))))
        top = max(0, min(height - 1, int(round(y1 * height))))
        right = max(left + 1, min(width, int(round(x2 * width))))
        bottom = max(top + 1, min(height, int(round(y2 * height))))
        payload = self._encode_snapshot_payload(array[top:bottom, left:right])
        result = self._store_snapshot_payload(binding, payload, ts, trigger="zone-crop")
        result["crop_box"] = [round(value, 6) for value in (x1, y1, x2, y2)]
        result["crop_pixels"] = [left, top, right, bottom]
        return result

    def on_frame(self, camera: dict[str, Any], frame, ts: float) -> None:
        with self._lock:
            bindings = tuple(self._bindings)
        due: list[_Binding] = []
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_stream":
                continue
            if str(binding.camera.get("id")) != str(camera.get("id")):
                continue
            interval = max(1.0, min(float(binding.settings.get("sample_interval_seconds", 30)), 86400.0))
            if binding.last_sample_at and ts - binding.last_sample_at < interval:
                continue
            binding.last_sample_at = ts
            due.append(binding)
        if not due:
            return
        try:
            import numpy as np

            base_metrics = self._frame_metrics(frame)
            array = np.asarray(frame)
            y_step = max(1, array.shape[0] // 90)
            x_step = max(1, array.shape[1] // 160)
            sample = np.ascontiguousarray(array[::y_step, ::x_step][:90, :160])
            frame_hash = hashlib.sha256(sample.tobytes()).hexdigest()
        except Exception as exc:
            for binding in due:
                binding.decode_errors += 1
                self._failures[binding.function_id] = type(exc).__name__
            return
        cache_bindings = [
            binding
            for binding in due
            if binding.manifest["api"]["profile"] == "snapshot_capture"
            and binding.function_id in {"manual-review-snapshot", "snapshot-last-good-frame"}
            and binding.camera.get("privacy_mode") != "skeleton"
        ]
        if cache_bindings:
            try:
                payload = self._encode_snapshot_payload(frame)
                if len(payload) <= 25 * 1024 * 1024:
                    self._latest_snapshot_payloads[str(camera.get("id") or "")] = (float(ts), payload)
            except Exception as exc:
                for binding in cache_bindings:
                    self._failures[binding.function_id] = type(exc).__name__
        for binding in due:
            try:
                previous = binding.last_metrics or {}
                gap = ts - binding.last_frame_at if binding.last_frame_at > 0 else 0.0
                duplicate = bool(binding.last_frame_hash and frame_hash == binding.last_frame_hash)
                binding.duplicate_streak = binding.duplicate_streak + 1 if duplicate else 0
                metrics = dict(base_metrics)
                metrics.update(
                    {
                        "first_sample": 1.0 if binding.frame_count == 0 else 0.0,
                        "startup_latency_seconds": max(0.0, ts - self._started_at) if binding.frame_count == 0 else 0.0,
                        "frame_gap_seconds": max(0.0, gap),
                        "effective_fps": 1.0 / gap if gap > 0 else 0.0,
                        "duplicate_frame": 1.0 if duplicate else 0.0,
                        "duplicate_streak": float(binding.duplicate_streak),
                        "resolution_changed": 1.0
                        if previous
                        and (previous.get("width"), previous.get("height"))
                        != (metrics["width"], metrics["height"])
                        else 0.0,
                        "frame_size_changed": 1.0
                        if previous and previous.get("frame_bytes") != metrics["frame_bytes"]
                        else 0.0,
                        "aspect_ratio_changed": 1.0
                        if previous
                        and abs(previous.get("aspect_ratio", metrics["aspect_ratio"]) - metrics["aspect_ratio"])
                        >= 0.01
                        else 0.0,
                        "luminance_delta": abs(
                            previous.get("luminance", metrics["luminance"]) - metrics["luminance"]
                        )
                        if previous
                        else 0.0,
                        "color_delta": max(
                            abs(previous.get(key, metrics[key]) - metrics[key])
                            for key in ("blue_mean", "green_mean", "red_mean")
                        )
                        if previous
                        else 0.0,
                    }
                )
                profile = binding.manifest["api"]["profile"]
                if profile == "snapshot_capture":
                    if binding.function_id == "snapshot-zone-crop":
                        snapshot = self._capture_zone_snapshot(binding, frame, ts)
                        if snapshot is None:
                            continue
                        meta = {
                            "status": "stored",
                            "write_ok": True,
                            "suppressed": False,
                            "camera_id": str(camera.get("id") or "")[:128],
                            "observed_at": round(ts, 3),
                            **snapshot,
                        }
                        self._fire(
                            binding,
                            binding.manifest["name"],
                            f"A configured local zone crop was stored for {camera.get('name', 'the configured camera')}.",
                            meta,
                        )
                        self._emit_snapshot_governance(str(camera.get("id") or ""), meta)
                        self._failures.pop(binding.function_id, None)
                        continue
                    scheduled, day = self._scheduled_snapshot_due(binding, ts)
                    if not scheduled:
                        continue
                    snapshot = self._capture_snapshot(binding, frame, ts, trigger="scheduled")
                    if snapshot is None:
                        continue
                    binding.last_schedule_day = day
                    self._fire(
                        binding,
                        binding.manifest["name"],
                        f"A scheduled local snapshot was stored for {camera.get('name', 'the configured camera')}.",
                        {"observed_at": round(ts, 3), **snapshot},
                    )
                    self._failures.pop(binding.function_id, None)
                    continue
                elif profile == "snapshot_governance":
                    directory = self.evidence_root / "snapshots"
                    files = list(directory.glob("*.jpg")) if directory.is_dir() else []
                    metrics = {
                        "snapshot_count": float(len(files)),
                        "snapshot_bytes": float(sum(path.stat().st_size for path in files)),
                    }
                if self._stream_condition(binding.function_id, metrics, binding.settings):
                    safe_metrics = {
                        key: round(float(value), 4)
                        for key, value in metrics.items()
                        if isinstance(value, (int, float)) and math.isfinite(float(value))
                    }
                    self._fire(
                        binding,
                        binding.manifest["name"],
                        f"A local RTSP sample produced an observation for {camera.get('name', 'the configured camera')}.",
                        {"observed_at": round(ts, 3), "metrics": safe_metrics},
                        frame=frame if profile not in {"snapshot_capture", "snapshot_governance"} else None,
                    )
                self._failures.pop(binding.function_id, None)
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__
            finally:
                binding.last_frame_at = ts
                binding.last_frame_hash = frame_hash
                binding.last_metrics = dict(base_metrics)
                binding.frame_count += 1

    def _handle_last_good_snapshot(
        self,
        camera: dict[str, Any],
        event: str,
        observed_at: float,
    ) -> None:
        if event not in {"connect_failed", "decode_error", "reconnecting"}:
            return
        camera_id = str(camera.get("id") or "")
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            if binding.function_id != "snapshot-last-good-frame":
                continue
            if binding.manifest["api"]["profile"] != "snapshot_capture":
                continue
            if str(binding.camera.get("id") or "") != camera_id:
                continue
            if binding.camera.get("privacy_mode") == "skeleton":
                count = self._snapshot_suppressed.get(camera_id, 0) + 1
                self._snapshot_suppressed[camera_id] = count
                meta = {
                    "status": "suppressed",
                    "suppressed": True,
                    "suppressed_count": count,
                    "camera_id": camera_id[:128],
                    "stream_event": event,
                }
                self._emit_snapshot_governance(camera_id, meta)
                continue
            latest = self._latest_snapshot_payloads.get(camera_id)
            if latest is None:
                self._failures[binding.function_id] = "SnapshotFrameUnavailable"
                continue
            frame_ts, payload = latest
            try:
                snapshot = self._store_snapshot_payload(
                    binding,
                    payload,
                    frame_ts,
                    trigger="stream-health-failure",
                )
            except Exception as exc:
                self._failures[binding.function_id] = type(exc).__name__
                self._emit_snapshot_governance(
                    camera_id,
                    {
                        "status": "failed",
                        "write_ok": False,
                        "camera_id": camera_id[:128],
                        "stream_event": event,
                        "error_class": type(exc).__name__,
                    },
                )
                continue
            meta = {
                "status": "stored",
                "write_ok": True,
                "suppressed": False,
                "camera_id": camera_id[:128],
                "stream_event": event,
                "observed_at": round(float(observed_at), 3),
                **snapshot,
            }
            self._fire(
                binding,
                binding.manifest["name"],
                f"The last successfully decoded local frame was retained after {event.replace('_', ' ')} for {binding.camera.get('name', 'the configured camera')}.",
                meta,
            )
            self._emit_snapshot_governance(camera_id, meta)
            self._failures.pop(binding.function_id, None)

    def on_stream_status(self, camera: dict[str, Any], status: dict[str, Any], ts: float) -> None:
        event = str(status.get("event") or "")
        if event not in {"connect_failed", "connected", "decode_error", "reconnecting"}:
            return
        camera_id = str(camera.get("id") or "")
        self._handle_last_good_snapshot(camera, event, ts)
        with self._lock:
            bindings = tuple(self._bindings)
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_stream":
                continue
            if str(binding.camera.get("id") or "") != camera_id:
                continue
            binding.stream_status_count += 1
            if event == "decode_error":
                binding.decode_errors += 1
            if event == "reconnecting":
                binding.reconnect_count += 1
            meta: dict[str, Any] = {"event": event, "observed_at": round(float(ts), 3)}
            should_fire = False
            if binding.function_id == "rtsp-connectivity-probe" and event in {"connect_failed", "connected"}:
                meta["connected"] = event == "connected"
                should_fire = True
            elif binding.function_id == "rtsp-startup-latency" and event == "connected":
                latency = max(0.0, min(float(status.get("latency_seconds", 0)), 3600.0))
                meta["latency_seconds"] = round(latency, 3)
                should_fire = True
            elif binding.function_id == "rtsp-decode-error-rate" and event == "decode_error":
                meta["decode_error_count"] = binding.decode_errors
                meta["decode_error_rate"] = round(
                    binding.decode_errors / max(1, binding.stream_status_count), 4
                )
                should_fire = True
            elif binding.function_id == "rtsp-reconnect-rate" and event == "reconnecting":
                meta["reconnect_count"] = binding.reconnect_count
                should_fire = True
            if should_fire:
                self._fire(
                    binding,
                    binding.manifest["name"],
                    f"The local RTSP worker reported {event.replace('_', ' ')} for {camera.get('name', 'the configured camera')}.",
                    meta,
                )

    def _emit_snapshot_governance(self, camera_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            bindings = tuple(self._bindings)
        status = str(meta.get("status") or "")
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_stream":
                continue
            if binding.manifest["api"]["profile"] != "snapshot_governance":
                continue
            if str(binding.camera.get("id") or "") != camera_id:
                continue
            should_fire = False
            if binding.function_id == "snapshot-privacy-suppression-audit":
                should_fire = status == "suppressed"
            elif binding.function_id == "snapshot-write-health":
                should_fire = status in {"stored", "failed"}
            elif binding.function_id in {"snapshot-checksum-manifest", "snapshot-payload-size-audit"}:
                should_fire = status == "stored"
            if should_fire:
                self._fire(
                    binding,
                    binding.manifest["name"],
                    f"The local snapshot workflow recorded {status} for {binding.camera.get('name', 'the configured camera')}.",
                    dict(meta),
                )

    def request_snapshot(self, function_id: str, camera_id: str, *, request_id: str) -> dict[str, Any]:
        binding = self._binding(function_id, "protect_stream", camera_id=camera_id)
        if binding.manifest["api"]["profile"] != "snapshot_capture" or function_id != "manual-review-snapshot":
            raise APIRuntimeError("function_not_snapshot_request", "function is not a manual snapshot request")
        if str(binding.camera.get("id") or "") != str(camera_id):
            raise APIRuntimeError("camera_not_configured", "camera is not configured for this function")
        if not isinstance(request_id, str) or not _SAFE_ID.fullmatch(request_id):
            raise APIRuntimeError("snapshot_request_invalid", "snapshot request identifier is invalid")
        with self._lock:
            if request_id in self._snapshot_request_ids:
                raise APIRuntimeError("duplicate_snapshot_request", "snapshot request was already processed")
        camera_key = str(camera_id)
        if binding.camera.get("privacy_mode") == "skeleton":
            count = self._snapshot_suppressed.get(camera_key, 0) + 1
            self._snapshot_suppressed[camera_key] = count
            meta = {
                "status": "suppressed",
                "suppressed": True,
                "suppressed_count": count,
                "camera_id": camera_key[:128],
                "request_id": request_id,
            }
            with self._lock:
                self._snapshot_request_ids.add(request_id)
            self._fire(
                binding,
                binding.manifest["name"],
                f"A manual snapshot request was suppressed by privacy mode for {binding.camera.get('name', 'the configured camera')}.",
                meta,
            )
            self._emit_snapshot_governance(camera_key, meta)
            return dict(meta)
        latest = self._latest_snapshot_payloads.get(camera_key)
        if latest is None:
            raise APIRuntimeError("snapshot_frame_unavailable", "no recent decoded frame is available")
        frame_ts, payload = latest
        max_age = max(1.0, min(float(binding.settings.get("max_frame_age_seconds", 60)), 3600.0))
        if max(0.0, float(self.clock()) - frame_ts) > max_age:
            raise APIRuntimeError("snapshot_frame_stale", "the most recent decoded frame is stale")
        try:
            snapshot = self._store_snapshot_payload(binding, payload, frame_ts, trigger="manual")
        except Exception as exc:
            meta = {
                "status": "failed",
                "write_ok": False,
                "camera_id": camera_key[:128],
                "request_id": request_id,
                "error_class": type(exc).__name__,
            }
            self._emit_snapshot_governance(camera_key, meta)
            raise APIRuntimeError("snapshot_write_failed", "snapshot could not be stored") from None
        meta = {
            "status": "stored",
            "write_ok": True,
            "suppressed": False,
            "camera_id": camera_key[:128],
            "request_id": request_id,
            **snapshot,
        }
        with self._lock:
            self._snapshot_request_ids.add(request_id)
        self._fire(
            binding,
            binding.manifest["name"],
            f"A manual local snapshot was stored for {binding.camera.get('name', 'the configured camera')}.",
            meta,
        )
        self._emit_snapshot_governance(camera_key, meta)
        return dict(meta)

    def _binding(
        self,
        function_id: str,
        runner: str,
        *,
        camera_id: str | None = None,
        door_id: str | None = None,
    ) -> _Binding:
        candidates = [
            binding
            for binding in self._bindings
            if binding.function_id == function_id
            and binding.manifest["api"]["runner"] == runner
        ]
        if not candidates:
            raise APIRuntimeError("function_not_configured", "requested API function is not configured")
        if camera_id is not None:
            for binding in candidates:
                if str(binding.camera.get("id") or "") == str(camera_id):
                    return binding
            raise APIRuntimeError("camera_not_configured", "camera is not configured for this function")
        if door_id is not None:
            for binding in candidates:
                allowlist = binding.settings.get("door_allowlist") or []
                if isinstance(allowlist, list) and door_id in allowlist:
                    return binding
            raise APIRuntimeError("door_not_allowed", "door is not allowlisted for this function")
        return candidates[0]

    def _append_clip_record(self, record: dict[str, Any]) -> None:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        descriptor = os.open(self._clip_index_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _clip_storage(directory: Path) -> int:
        return sum(path.stat().st_size for path in directory.glob("*.mp4") if path.is_file())

    @staticmethod
    def _prune_clips(directory: Path, *, now: float, retention_days: int) -> int:
        cutoff = now - retention_days * 86400
        pruned = 0
        for path in directory.glob("*.mp4"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    pruned += 1
            except FileNotFoundError:
                continue
        return pruned

    def _emit_clip_governance(self, camera_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            bindings = tuple(self._bindings)
        status = str(meta.get("status") or "")
        for binding in bindings:
            if binding.manifest["api"]["runner"] != "protect_evidence":
                continue
            if str(binding.camera.get("id") or "") != camera_id:
                continue
            function_id = binding.function_id
            should_fire = False
            if function_id in {
                "clip-export-checksum-manifest",
                "clip-export-daily-manifest",
                "clip-export-duration-cap",
                "clip-export-index",
                "clip-export-camera-validation",
                "clip-export-filename-normalizer",
                "clip-export-integrity-probe",
                "clip-export-latency-metrics",
                "clip-export-queue",
            }:
                should_fire = status in {"exported", "reused"}
            elif function_id == "clip-export-overlap-deduper":
                should_fire = bool(meta.get("reused"))
            elif function_id == "clip-export-retention-pruner":
                should_fire = int(meta.get("pruned_count") or 0) > 0
            elif function_id == "clip-export-storage-quota":
                should_fire = status in {"exported", "reused", "quota_rejected"}
            elif function_id in {"clip-export-failure-digest", "clip-export-retry-ledger"}:
                should_fire = status in {"failed", "quota_rejected"}
            if should_fire:
                self._fire(
                    binding,
                    binding.manifest["name"],
                    f"The local Protect clip workflow recorded {status.replace('_', ' ')} for {binding.camera.get('name', 'the configured camera')}.",
                    dict(meta),
                )

    def export_clip(self, function_id: str, camera_id: str, start_ms: int, end_ms: int) -> dict[str, Any]:
        binding = self._binding(function_id, "protect_evidence", camera_id=camera_id)
        if binding.manifest["api"]["profile"] != "clip_export" or function_id != "manual-bounded-clip-export":
            raise APIRuntimeError("function_not_exportable", "function is not a manual single-camera export")
        return self._export_clip_binding(binding, camera_id, start_ms, end_ms)

    def _export_clip_binding(
        self,
        binding: _Binding,
        camera_id: str,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        if str(binding.camera.get("id")) != str(camera_id):
            raise APIRuntimeError("camera_not_configured", "camera is not configured for this function")
        if not isinstance(start_ms, int) or not isinstance(end_ms, int) or not 0 < end_ms - start_ms <= _MAX_CLIP_DURATION_MS:
            raise APIRuntimeError("clip_window_invalid", "clip export window is invalid")
        if self.protect_client is None:
            raise APIRuntimeError("protect_unavailable", "Protect clip export is unavailable")
        directory = self.evidence_root / "clips"
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        name = hashlib.sha256(f"{camera_id}:{start_ms}:{end_ms}".encode()).hexdigest()
        destination = (directory / f"{name}.mp4").resolve()
        if not destination.is_relative_to(self.evidence_root):
            raise APIRuntimeError("evidence_path_invalid", "evidence path is invalid")
        maximum = max(1, min(int(binding.settings.get("max_clip_bytes", 104_857_600)), _MAX_CLIP_BYTES))
        quota = max(maximum, min(int(binding.settings.get("storage_quota_bytes", 5 * 1024 * 1024 * 1024)), 50 * 1024 * 1024 * 1024))
        retention_days = max(1, min(int(binding.settings.get("retention_days", 30)), 3650))
        timeout_seconds = max(1.0, min(float(binding.settings.get("timeout_seconds", 60)), 120.0))
        started = time.monotonic()
        with self._evidence_lock:
            pruned = self._prune_clips(directory, now=float(self.clock()), retention_days=retention_days)
            if destination.is_file():
                size = destination.stat().st_size
                if 0 < size <= maximum:
                    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                    meta = {
                        "status": "reused",
                        "camera_id": str(camera_id)[:128],
                        "duration_seconds": round((end_ms - start_ms) / 1000.0, 3),
                        "path": destination.relative_to(self.evidence_root).as_posix(),
                        "bytes": size,
                        "sha256": digest,
                        "reused": True,
                        "pruned_count": pruned,
                        "storage_bytes": self._clip_storage(directory),
                        "storage_quota_bytes": quota,
                        "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                    }
                    self._append_clip_record(meta)
                    self._emit_clip_governance(str(camera_id), meta)
                    return dict(meta)
                destination.unlink(missing_ok=True)
            result = self.protect_client.download_clip(
                camera_id,
                start_ms,
                end_ms,
                str(destination),
                max_bytes=maximum,
                timeout_seconds=timeout_seconds,
            )
            if result is None or not destination.is_file():
                destination.unlink(missing_ok=True)
                meta = {
                    "status": "failed",
                    "camera_id": str(camera_id)[:128],
                    "duration_seconds": round((end_ms - start_ms) / 1000.0, 3),
                    "reused": False,
                    "pruned_count": pruned,
                    "storage_bytes": self._clip_storage(directory),
                    "storage_quota_bytes": quota,
                    "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                }
                self._append_clip_record(meta)
                self._emit_clip_governance(str(camera_id), meta)
                raise APIRuntimeError("clip_export_failed", "Protect clip export failed")
            size = destination.stat().st_size
            if size > maximum:
                destination.unlink(missing_ok=True)
                raise APIRuntimeError("clip_too_large", "Protect clip exceeded the configured limit")
            os.chmod(destination, 0o600)
            storage = self._clip_storage(directory)
            if storage > quota:
                destination.unlink(missing_ok=True)
                meta = {
                    "status": "quota_rejected",
                    "camera_id": str(camera_id)[:128],
                    "duration_seconds": round((end_ms - start_ms) / 1000.0, 3),
                    "bytes": size,
                    "reused": False,
                    "pruned_count": pruned,
                    "storage_bytes": self._clip_storage(directory),
                    "storage_quota_bytes": quota,
                    "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                }
                self._append_clip_record(meta)
                self._emit_clip_governance(str(camera_id), meta)
                raise APIRuntimeError("clip_storage_quota", "clip storage quota would be exceeded")
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            meta = {
                "status": "exported",
                "camera_id": str(camera_id)[:128],
                "duration_seconds": round((end_ms - start_ms) / 1000.0, 3),
                "path": destination.relative_to(self.evidence_root).as_posix(),
                "bytes": size,
                "sha256": digest,
                "reused": False,
                "pruned_count": pruned,
                "storage_bytes": storage,
                "storage_quota_bytes": quota,
                "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
            }
            self._append_clip_record(meta)
            self._emit_clip_governance(str(camera_id), meta)
            return dict(meta)

    def _load_request_ids(self) -> None:
        try:
            for line in self._audit_path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if isinstance(record, dict) and isinstance(record.get("request_id"), str):
                    self._request_ids.add(record["request_id"])
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, ValueError):
            raise APIRuntimeError("control_audit_invalid", "access-control audit is invalid")

    def _append_audit(self, record: dict[str, Any]) -> None:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        descriptor = os.open(self._audit_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def request_unlock(self, function_id: str, door_id: str, *, reason: str, request_id: str) -> dict[str, Any]:
        if not _SAFE_ID.fullmatch(str(door_id)) or not _SAFE_ID.fullmatch(str(request_id)):
            raise APIRuntimeError("control_request_invalid", "access-control request is invalid")
        binding = self._binding(function_id, "access_unlock_request", door_id=door_id)
        with self._lock:
            if request_id in self._request_ids:
                raise APIRuntimeError("duplicate_request", "access-control request was already processed")
            allowlist = binding.settings.get("door_allowlist") or []
            if not isinstance(allowlist, list) or door_id not in allowlist:
                raise APIRuntimeError("door_not_allowed", "door is not allowlisted for this function")
            required = binding.settings.get("reason_required", True) is not False
            if required and (not isinstance(reason, str) or not reason.strip() or len(reason) > 500):
                raise APIRuntimeError("reason_required", "a bounded operator reason is required")
            if self.access_control is None:
                raise APIRuntimeError("access_control_unavailable", "UniFi Access control is unavailable")
            accepted = self.access_control.unlock(door_id) is True
            record = {
                "schema": "nexus.access-control-audit/v1",
                "request_id": request_id,
                "door_id": door_id,
                "function_id": function_id,
                "reason_sha256": hashlib.sha256(reason.strip().encode()).hexdigest(),
                "requested_at": round(float(self.clock()), 3),
                "accepted": accepted,
            }
            self._append_audit(record)
            self._request_ids.add(request_id)
            if not accepted:
                raise APIRuntimeError("unlock_failed", "UniFi Access rejected or failed the unlock request")
            return {"request_id": request_id, "door_id": door_id, "accepted": True}
