"""Alert engine: dedup, severity routing, Base44 + webhook dispatch, clip retention."""
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
        self.dedup_seconds = (config.get("alerts") or {}).get("dedup_seconds", 120)
        self.data_dir = Path(data_dir)
        (self.data_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        self._recent = {}
        self._lock = threading.Lock()
        self.sent = 0
        self.suppressed = 0

    def _dedup_key(self, camera, detector):
        return f"{camera}:{detector}"

    def _save_snapshot(self, frame, camera, detector) -> str | None:
        if frame is None:
            return None
        try:
            # Sanitize filename components to prevent path traversal
            safe_detector = detector.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("..", "_")
            safe_camera = camera.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("..", "_")
            name = f"{safe_detector}_{safe_camera}_{int(time.time())}.jpg"
            path = self.data_dir / "snapshots" / name
            cv2.imwrite(str(path), frame)
            return str(path)
        except Exception as exc:
            log.warning("snapshot failed: %s", exc)
            return None

    def fire(self, *, site: str, camera: dict, detector: str, title: str,
             detail: str, frame=None, meta: dict | None = None):
        key = self._dedup_key(camera["name"], detector)
        now = time.time()
        with self._lock:
            last = self._recent.get(key, 0)
            if now - last < self.dedup_seconds:
                self.suppressed += 1
                return False
            self._recent[key] = now

        severity = self.severities.get(detector, "warning")
        snapshot = self._save_snapshot(frame, camera["id"], detector)
        payload = {
            "internalToken": self.token,
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

        delivered = []
        if self.url and self.token and "change-me" not in self.token:
            try:
                r = requests.post(self.url, json=payload, timeout=15)
                delivered.append(f"base44:{r.status_code}")
            except Exception as exc:
                log.warning("Base44 dispatch failed: %s", exc)
                delivered.append("base44:error")
        if self.extra_webhook:
            try:
                r = requests.post(self.extra_webhook, json=payload, timeout=10)
                delivered.append(f"webhook:{r.status_code}")
            except Exception as exc:
                log.warning("webhook dispatch failed: %s", exc)

        self.sent += 1
        log.warning("ALERT [%s/%s] %s — %s (%s)",
                    severity.upper(), detector, title, camera["name"], ",".join(delivered) or "log-only")
        return True

    def stats(self):
        return {"alerts_sent": self.sent, "alerts_suppressed": self.suppressed}
