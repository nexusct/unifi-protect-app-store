"""UniFi Protect API client: camera discovery, RTSP mapping, events, clips."""
import logging
import hashlib
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict

import requests

from runtime_settings import runtime_setting

log = logging.getLogger("unifi_protect")

_MAX_EVENT_ID_LENGTH = 256
_MAX_EVENT_VALUES = 16
_MAX_SEEN_EVENTS = 4096
_SAFE_EVENT_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
_SENSITIVE_EVENT_FIELD_TOKENS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "rtsp",
    "secret",
    "token",
)


def _safe_event_value(value) -> str:
    text = str(value or "").strip()[:80]
    return "".join(character for character in text if character.isalnum() or character in "-_:.")


def normalize_protect_event(event: dict) -> dict | None:
    """Project a controller event into a bounded, non-secret local vocabulary."""
    if not isinstance(event, dict):
        return None
    raw_ts = event.get("start") or event.get("timestamp") or event.get("end") or 0
    try:
        ts = int(float(raw_ts))
    except (TypeError, ValueError, OverflowError):
        return None
    if ts <= 0:
        return None
    if ts < 100_000_000_000:
        ts *= 1000
    camera = event.get("camera") or event.get("cameraId") or event.get("camera_id") or ""
    if isinstance(camera, dict):
        camera = camera.get("id") or ""
    camera_id = _safe_event_value(camera)
    event_type = _safe_event_value(event.get("type"))
    if not camera_id or not event_type:
        return None
    smart = event.get("smartDetectTypes") or event.get("smart_types") or []
    if isinstance(smart, str):
        smart = [smart]
    if not isinstance(smart, list):
        smart = []
    smart_types = sorted(
        {
            normalized
            for value in smart[:_MAX_EVENT_VALUES]
            if (normalized := _safe_event_value(value).casefold())
        }
    )
    raw_score = event.get("score")
    score = 0.0
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) and math.isfinite(float(raw_score)):
        score = max(0.0, min(float(raw_score), 100.0))
    identifier = _safe_event_value(event.get("id") or event.get("_id"))[:_MAX_EVENT_ID_LENGTH]
    if not identifier:
        identifier = hashlib.sha256(
            json.dumps(
                [ts, camera_id, event_type, smart_types],
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    duration_seconds = 0.0
    try:
        start_value = event.get("start")
        end_value = event.get("end")
        if not isinstance(start_value, (int, float, str)) or not isinstance(end_value, (int, float, str)):
            raise TypeError("event endpoints must be numeric")
        raw_start = float(start_value)
        raw_end = float(end_value)
        if math.isfinite(raw_start) and math.isfinite(raw_end):
            if raw_start < 100_000_000_000:
                raw_start *= 1000
            if raw_end < 100_000_000_000:
                raw_end *= 1000
            if raw_end >= raw_start:
                duration_seconds = min((raw_end - raw_start) / 1000.0, 86400.0)
    except (TypeError, ValueError, OverflowError):
        pass
    source_fields = sorted(
        str(key)
        for key in list(event)[:128]
        if isinstance(key, str)
        and _SAFE_EVENT_FIELD.fullmatch(key)
        and not any(token in key.casefold() for token in _SENSITIVE_EVENT_FIELD_TOKENS)
    )[:64]
    return {
        "id": identifier,
        "ts": ts,
        "camera_id": camera_id,
        "type": event_type,
        "smart_types": smart_types,
        "score": score,
        "duration_seconds": round(duration_seconds, 3),
        "start_present": "start" in event and event.get("start") not in (None, ""),
        "end_present": "end" in event and event.get("end") not in (None, ""),
        "camera_reference_present": any(
            key in event and event.get(key) not in (None, "")
            for key in ("camera", "cameraId", "camera_id")
        ),
        "source_fields": source_fields,
    }


class ProtectClient:
    def __init__(
        self,
        *,
        host=None,
        port=None,
        username=None,
        password=None,
        verify=None,
        session=None,
    ):
        self.host = str(host or runtime_setting("UNIFI_PROTECT_HOST", required=True)).strip()
        self.port = int(port or runtime_setting("UNIFI_PROTECT_PORT", "443"))
        self.username = str(username or runtime_setting("UNIFI_PROTECT_USERNAME", required=True))
        self.password = str(password or runtime_setting("UNIFI_PROTECT_PASSWORD", required=True))
        if verify is None:
            configured_verify = str(runtime_setting("UNIFI_PROTECT_VERIFY_SSL", "true")).strip()
            lowered = configured_verify.lower()
            verify = True if lowered in {"", "true", "1", "yes", "on"} else (
                False if lowered in {"false", "0", "no", "off"} else configured_verify
            )
        self.verify = verify
        address = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        self._address = address
        self.base = f"https://{address}:{self.port}/proxy/protect/api"
        self.session = session or requests.Session()
        self.session.verify = self.verify
        self.session.headers.update({"Accept": "application/json"})
        self._login()

    def _login(self):
        r = self.session.post(
            f"https://{self._address}:{self.port}/api/auth/login",
            json={
                "username": self.username,
                "password": self.password,
            },
            timeout=15,
        )
        r.raise_for_status()
        csrf = r.headers.get("x-csrf-token") or r.headers.get("X-CSRF-Token")
        if csrf:
            self.session.headers.update({"X-CSRF-Token": csrf})
        log.info("Protect login OK (%s)", self.host)

    def cameras(self):
        """Return canonical camera metadata and the lowest enabled RTSP/S feed."""
        r = self.session.get(f"{self.base}/cameras", timeout=15)
        r.raise_for_status()
        out = []
        for cam in r.json():
            channels = cam.get("channels") or []
            enabled = [ch for ch in channels if ch.get("rtspAlias") and ch.get("isRtspEnabled")]
            selected = min(
                enabled,
                key=lambda ch: max(1, int(ch.get("width") or 0)) * max(1, int(ch.get("height") or 0)),
                default=None,
            )
            rtsp = f"rtsps://{self._address}:7441/{selected['rtspAlias']}" if selected else None
            out.append(
                {
                    "id": cam.get("id"),
                    "name": cam.get("name"),
                    "model": cam.get("type") or cam.get("modelKey") or "UniFi camera",
                    "state": cam.get("state") or "UNKNOWN",
                    "rtsp": rtsp,
                    "rtsp_enabled": selected is not None,
                    "stream": {
                        "width": int((selected or {}).get("width") or 0),
                        "height": int((selected or {}).get("height") or 0),
                        "fps": int((selected or {}).get("fps") or 0),
                    },
                }
            )
        return out

    def recent_events(self, since_ms: int, types=("motion", "smartDetectZone")):
        """Poll Protect events (motion/smart detections) since a timestamp."""
        params = {"start": since_ms, "limit": 100}
        r = self.session.get(f"{self.base}/events", params=params, timeout=15)
        if r.status_code != 200:
            log.warning("Protect events %s", r.status_code)
            return []
        return [e for e in r.json() if e.get("type") in types or not types]

    def clip_url(self, camera_id: str, start_ms: int, end_ms: int) -> str:
        return f"{self.base}/video/export?camera={camera_id}&start={start_ms}&end={end_ms}"

    def download_clip(
        self,
        camera_id: str,
        start_ms: int,
        end_ms: int,
        dest: str,
        *,
        max_bytes: int = 100 * 1024 * 1024,
        timeout_seconds: float = 60.0,
    ) -> str | None:
        destination = os.path.abspath(dest)
        partial = destination + ".partial"
        maximum = max(1, min(int(max_bytes), 500 * 1024 * 1024))
        timeout = max(1.0, min(float(timeout_seconds), 120.0))
        try:
            try:
                os.unlink(partial)
            except FileNotFoundError:
                pass
            descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            total = 0
            try:
                with self.session.get(
                    self.clip_url(camera_id, start_ms, end_ms),
                    stream=True,
                    timeout=(timeout, timeout),
                ) as response:
                    response.raise_for_status()
                    with os.fdopen(descriptor, "wb") as output:
                        descriptor = -1
                        for chunk in response.iter_content(1 << 20):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > maximum:
                                raise ValueError("clip exceeds configured byte limit")
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                os.replace(partial, destination)
                os.chmod(destination, 0o600)
                directory = os.open(os.path.dirname(destination) or ".", os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return dest
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        except Exception as exc:
            try:
                os.unlink(partial)
            except FileNotFoundError:
                pass
            log.warning("clip export failed (%s)", type(exc).__name__)
            return None


class ProtectEventPoller:
    """Bounded local Protect-event poller with monotonic watermark and dedupe."""

    def __init__(
        self,
        on_event,
        *,
        on_poll=None,
        client=None,
        start_ms: int | None = None,
        poll_seconds: float = 2.0,
    ):
        self.on_event = on_event
        self.on_poll = on_poll
        self.client = client
        self.poll_seconds = max(0.5, min(float(poll_seconds), 60.0))
        self.last_seen_ms = int(start_ms if start_ms is not None else time.time() * 1000)
        self._seen = OrderedDict()
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self.client is None:
            try:
                self.client = ProtectClient()
            except Exception:
                log.warning("Protect event poller disabled; local API connection unavailable")
                return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="protect-event-poller")
        self._thread.start()
        log.info("Protect event poller started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.warning("Protect event poll failed")
            self._stop.wait(self.poll_seconds)

    def poll_once(self) -> int:
        if self.client is None:
            return 0
        started = time.monotonic()
        try:
            raw_events = self.client.recent_events(self.last_seen_ms, types=())
        except Exception:
            self._notify_poll(
                {
                    "ok": False,
                    "poll_latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                    "raw_event_count": 0,
                    "emitted_event_count": 0,
                    "duplicate_event_count": 0,
                    "invalid_event_count": 0,
                    "page_saturated": False,
                    "last_seen_ms": self.last_seen_ms,
                }
            )
            raise
        raw_list = list(raw_events or [])
        emitted = 0
        duplicates = 0
        invalid = 0
        for raw in raw_list[:100]:
            event = normalize_protect_event(raw)
            if event is None:
                invalid += 1
                continue
            self.last_seen_ms = max(self.last_seen_ms, int(event["ts"]) + 1)
            identifier = event["id"]
            if identifier in self._seen:
                duplicates += 1
                continue
            self._seen[identifier] = event["ts"]
            self.on_event(event)
            emitted += 1
        while len(self._seen) > _MAX_SEEN_EVENTS:
            self._seen.popitem(last=False)
        self._notify_poll(
            {
                "ok": True,
                "poll_latency_ms": round((time.monotonic() - started) * 1000.0, 3),
                "raw_event_count": min(len(raw_list), 100_000),
                "emitted_event_count": emitted,
                "duplicate_event_count": duplicates,
                "invalid_event_count": invalid,
                "page_saturated": len(raw_list) >= 100,
                "last_seen_ms": self.last_seen_ms,
            }
        )
        return emitted

    def _notify_poll(self, status: dict) -> None:
        if self.on_poll is None:
            return
        try:
            self.on_poll(status)
        except Exception:
            log.warning("Protect poll health callback failed")
