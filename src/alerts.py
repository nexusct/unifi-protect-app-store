"""Alert engine: dedup, severity routing, and optional snapshot dispatch."""
import base64
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

import cv2
import requests

log = logging.getLogger("alerts")


class AlertEngine:
    def __init__(self, config: dict, data_dir: str):
        self.url = os.environ.get("BASE44_ALERT_URL", "")
        self.token = os.environ.get("BASE44_INTERNAL_TOKEN", "")
        self.extra_webhook = os.environ.get("EXTRA_WEBHOOK_URL", "")
        self.severities = (config.get("alerts") or {}).get("severities", {})
        alert_config = config.get("alerts") or {}
        self.dedup_seconds = alert_config.get("dedup_seconds", 120)
        self.snapshot_retention_days = float(alert_config.get("snapshot_retention_days", 7))
        self.snapshot_max_files = max(1, int(alert_config.get("snapshot_max_files", 1000)))
        self.snapshot_payload_max_bytes = max(
            0,
            int(alert_config.get("snapshot_payload_max_bytes", 1_048_576)),
        )
        self.outbox_max_events = max(1, int(alert_config.get("outbox_max_events", 100)))
        self.outbox_max_bytes = max(256, int(alert_config.get("outbox_max_bytes", 10_485_760)))
        self.outbox_max_occurrences_per_event = max(
            1,
            int(alert_config.get("outbox_max_occurrences_per_event", 1000)),
        )
        self.data_dir = Path(data_dir)
        (self.data_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        self.outbox_path = self.data_dir / "alert-outbox.json"
        self._recent = {}
        self._lock = threading.Lock()
        self.outbox_dropped = 0
        self._pending = self._load_outbox()
        self._destination_metrics = {}
        self.sent = 0
        self.failed = 0
        self.suppressed = 0
        self.retried = 0
        self.prune_storage()

    def _load_outbox(self):
        try:
            value = json.loads(self.outbox_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                self.outbox_dropped = max(0, int(value.get("dropped", 0)))
                value = value.get("pending", [])
            if not isinstance(value, list):
                return []
            pending = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                item["occurrences"] = min(
                    self.outbox_max_occurrences_per_event,
                    max(1, int(item.get("occurrences", 1))),
                )
                pending.append(item)
            return pending
        except FileNotFoundError:
            return []
        except Exception as exc:
            log.error("alert outbox could not be loaded: %s", exc)
            return []

    def _outbox_document(self):
        return {"version": 1, "dropped": self.outbox_dropped, "pending": self._pending}

    def _serialized_outbox(self):
        return json.dumps(self._outbox_document(), separators=(",", ":")).encode("utf-8")

    def _trim_outbox_bytes(self):
        dropped = 0
        while self._pending and len(self._serialized_outbox()) > self.outbox_max_bytes:
            item = self._pending.pop(0)
            dropped += item.get("occurrences", 1)
            self.outbox_dropped += item.get("occurrences", 1)
        if dropped:
            log.error("alert outbox byte capacity exceeded; dropped %d oldest occurrence(s)", dropped)

    def _persist_outbox(self):
        self._trim_outbox_bytes()
        serialized = self._serialized_outbox()
        if len(serialized) > self.outbox_max_bytes:
            raise RuntimeError("alert outbox metadata exceeds configured byte capacity")
        temporary = self.outbox_path.with_suffix(".tmp")
        temporary.write_bytes(serialized)
        os.replace(temporary, self.outbox_path)

    @staticmethod
    def _pending_id(destination, payload):
        identity = {
            "destination": destination,
            "cameraId": payload.get("cameraId"),
            "detector": payload.get("detector"),
            "title": payload.get("title"),
            "detail": payload.get("detail"),
            "meta": payload.get("meta"),
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _queue_failed(self, destination, payload):
        pending_id = self._pending_id(destination, payload)
        with self._lock:
            existing = next((item for item in self._pending if item.get("id") == pending_id), None)
            if existing is not None:
                if existing.get("occurrences", 1) < self.outbox_max_occurrences_per_event:
                    existing["occurrences"] = existing.get("occurrences", 1) + 1
                    existing["last_queued_at"] = time.time()
                else:
                    self.outbox_dropped += 1
                    log.error("alert outbox occurrence capacity exceeded; dropped identical occurrence")
                self._persist_outbox()
                return
            queued_at = time.time()
            self._pending.append({
                "id": pending_id,
                "destination": destination,
                "payload": payload,
                "occurrences": 1,
                "queued_at": queued_at,
                "last_queued_at": queued_at,
            })
            if len(self._pending) > self.outbox_max_events:
                overflow = len(self._pending) - self.outbox_max_events
                dropped = self._pending[:overflow]
                del self._pending[:overflow]
                self.outbox_dropped += sum(item.get("occurrences", 1) for item in dropped)
                log.error("alert outbox capacity exceeded; dropped %d oldest event(s)", overflow)
            self._persist_outbox()

    def pending_count(self):
        with self._lock:
            return len(self._pending)

    def pending_occurrence_count(self):
        with self._lock:
            return sum(item.get("occurrences", 1) for item in self._pending)

    @staticmethod
    def _empty_destination_metrics():
        return {
            "sent": 0,
            "failed": 0,
            "suppressed": 0,
            "retried": 0,
            "retry_failed": 0,
            "pending": 0,
        }

    def _destination_metric_locked(self, destination):
        return self._destination_metrics.setdefault(
            destination,
            self._empty_destination_metrics(),
        )

    def destination_stats(self):
        with self._lock:
            result = {
                destination: dict(values)
                for destination, values in self._destination_metrics.items()
            }
            for item in self._pending:
                destination = item.get("destination", "unknown")
                values = result.setdefault(destination, self._empty_destination_metrics())
                values["pending"] += 1
            return dict(sorted(result.items()))

    def delivery_readiness(self):
        """Summarize unresolved outbound delivery state for `/ready`."""
        configured = []
        degraded = set()
        if self.url:
            configured.append("base44")
            if not self.token or "change-me" in self.token.lower():
                degraded.add("base44")
        if self.extra_webhook:
            configured.append("webhook")
        with self._lock:
            pending_events = len(self._pending)
            pending_occurrences = sum(item.get("occurrences", 1) for item in self._pending)
            dropped = self.outbox_dropped
            degraded.update(item.get("destination", "unknown") for item in self._pending)
        return {
            "ok": not degraded and pending_events == 0 and dropped == 0,
            "configured": configured,
            "degraded_destinations": sorted(degraded),
            "pending_events": pending_events,
            "pending_occurrences": pending_occurrences,
            "dropped": dropped,
        }

    def _retry_destination(self, destination, payload):
        if destination == "base44":
            if not self.url or not self.token or "change-me" in self.token.lower():
                return False
            response = requests.post(
                self.url,
                json={**payload, "internalToken": self.token},
                timeout=15,
            )
            return 200 <= response.status_code < 300
        if destination == "webhook":
            if not self.extra_webhook:
                return False
            response = requests.post(self.extra_webhook, json=payload, timeout=10)
            return 200 <= response.status_code < 300
        return True

    def retry_pending(self):
        with self._lock:
            pending = list(self._pending)
        delivered_items = []
        for item in pending:
            try:
                if self._retry_destination(item["destination"], item["payload"]):
                    delivered_items.append(item)
                else:
                    with self._lock:
                        metrics = self._destination_metric_locked(item["destination"])
                        metrics["failed"] += 1
                        metrics["retry_failed"] += 1
            except Exception as exc:
                log.warning("pending %s alert retry failed: %s", item.get("destination"), exc)
                with self._lock:
                    metrics = self._destination_metric_locked(item.get("destination", "unknown"))
                    metrics["failed"] += 1
                    metrics["retry_failed"] += 1
        if delivered_items:
            with self._lock:
                delivered = {item["id"] for item in delivered_items}
                previous = self._pending
                self._pending = [item for item in self._pending if item.get("id") not in delivered]
                try:
                    self._persist_outbox()
                except Exception as exc:
                    self._pending = previous
                    log.error("alert outbox could not record successful retry: %s", exc)
                    return 0
                self.retried += len(delivered_items)
                for item in delivered_items:
                    metrics = self._destination_metric_locked(item["destination"])
                    metrics["sent"] += 1
                    metrics["retried"] += 1
        return len(delivered_items)

    def prune_storage(self, now=None):
        current = time.time() if now is None else float(now)
        files = sorted(
            (path for path in (self.data_dir / "snapshots").glob("*.jpg") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if self.snapshot_retention_days > 0:
            cutoff = current - self.snapshot_retention_days * 86400
            for path in list(files):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            files = [path for path in files if path.exists()]
        for path in files[self.snapshot_max_files:]:
            path.unlink(missing_ok=True)

    def _dedup_key(self, camera, detector, destination):
        return f"{camera}:{detector}:{destination}"

    def _save_snapshot(self, frame, camera, detector) -> str | None:
        if frame is None:
            return None
        try:
            name = f"{detector}_{camera}_{int(time.time())}.jpg".replace(" ", "_")
            path = self.data_dir / "snapshots" / name
            if not cv2.imwrite(str(path), frame):
                raise OSError("OpenCV did not write the snapshot")
            self.prune_storage()
            return str(path)
        except Exception as exc:
            log.warning("snapshot failed: %s", exc)
            return None

    def fire(self, *, site: str, camera: dict, detector: str, title: str,
             detail: str, frame=None, meta: dict | None = None):
        now = time.time()
        destinations = []
        if self.url:
            destinations.append("base44")
        if self.extra_webhook:
            destinations.append("webhook")
        if not destinations:
            destinations.append("log")

        due = []
        keys = {}
        with self._lock:
            for destination in destinations:
                key = self._dedup_key(camera["name"], detector, destination)
                keys[destination] = key
                if now - self._recent.get(key, 0) >= self.dedup_seconds:
                    self._recent[key] = now
                    due.append(destination)
                else:
                    self._destination_metric_locked(destination)["suppressed"] += 1
            if not due:
                self.suppressed += 1
                return False

        severity = self.severities.get(detector, "warning")
        snapshot_frame = None if camera.get("privacy_mode") == "skeleton" else frame
        snapshot = self._save_snapshot(snapshot_frame, camera["id"], detector)
        payload = {
            "source": "nexus-vision-ai",
            "site": site,
            "camera": camera["name"],
            "cameraId": camera["id"],
            "detector": detector,
            "severity": severity,
            "title": title,
            "detail": detail,
            "snapshotPath": snapshot,
            "meta": meta or {},
            "firedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
        if snapshot and self.snapshot_payload_max_bytes > 0:
            try:
                snapshot_path = Path(snapshot)
                with snapshot_path.open("rb") as snapshot_file:
                    snapshot_bytes = snapshot_file.read(self.snapshot_payload_max_bytes + 1)
                if len(snapshot_bytes) <= self.snapshot_payload_max_bytes:
                    payload["snapshot"] = {
                        "filename": snapshot_path.name,
                        "contentType": "image/jpeg",
                        "base64": base64.b64encode(snapshot_bytes).decode("ascii"),
                    }
                else:
                    log.warning(
                        "snapshot payload omitted: %s exceeds %d-byte cap",
                        snapshot_path.name,
                        self.snapshot_payload_max_bytes,
                    )
            except Exception as exc:
                log.warning("snapshot payload failed: %s", exc)

        attempts = []
        failures = []
        for destination in due:
            if destination == "log":
                attempts.append("log-only")
                continue
            if destination == "base44":
                if not self.token or "change-me" in self.token.lower():
                    attempts.append("base44:misconfigured")
                    failures.append(destination)
                    continue
                try:
                    response = requests.post(
                        self.url,
                        json={**payload, "internalToken": self.token},
                        timeout=15,
                    )
                    attempts.append(f"base44:{response.status_code}")
                    if not 200 <= response.status_code < 300:
                        failures.append(destination)
                        log.warning("Base44 dispatch returned HTTP %s", response.status_code)
                except Exception as exc:
                    failures.append(destination)
                    attempts.append("base44:error")
                    log.warning("Base44 dispatch failed: %s", exc)
                continue
            try:
                response = requests.post(self.extra_webhook, json=payload, timeout=10)
                attempts.append(f"webhook:{response.status_code}")
                if not 200 <= response.status_code < 300:
                    failures.append(destination)
                    log.warning("webhook dispatch returned HTTP %s", response.status_code)
            except Exception as exc:
                failures.append(destination)
                attempts.append("webhook:error")
                log.warning("webhook dispatch failed: %s", exc)

        delivered = not failures
        with self._lock:
            failed_destinations = set(failures)
            for destination in due:
                metrics = self._destination_metric_locked(destination)
                if destination in failed_destinations:
                    metrics["failed"] += 1
                else:
                    metrics["sent"] += 1
            if delivered:
                self.sent += 1
            else:
                self.failed += 1
                for destination in failures:
                    key = keys[destination]
                    if self._recent.get(key) == now:
                        self._recent.pop(key, None)
        for destination in failures:
            self._queue_failed(destination, payload)
        log.warning(
            "ALERT [%s/%s] %s — %s (%s)",
            severity.upper(), detector, title, camera["name"], ",".join(attempts),
        )
        return delivered

    def stats(self):
        return {
            "alerts_sent": self.sent,
            "alerts_failed": self.failed,
            "alerts_suppressed": self.suppressed,
        }
