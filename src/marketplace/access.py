"""Shared UniFi Access event helpers for cross-system marketplace functions.

Access reports what happened at the door (credential granted, credential
denied, door-state alarm, doorbell, remote unlock). Protect analytics report
what the camera observed. These helpers normalize the Access side — kind,
identity, timestamp, credential method — so every correlation module joins on
the same vocabulary instead of re-parsing firmware-specific event strings.

Nothing here concludes intent: `classify` reports the event kind the Access
controller supplied, and the correlation windows only bound which observations
a module considers alongside it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

GRANTED = "granted"
DENIED = "denied"
FORCED_OPEN = "forced_open"
HELD_OPEN = "held_open"
DOORBELL = "doorbell"
UNLOCK_COMMAND = "unlock_command"
DOOR_CLOSED = "door_closed"
OTHER = "other"

KINDS = (GRANTED, DENIED, FORCED_OPEN, HELD_OPEN, DOORBELL, UNLOCK_COMMAND, DOOR_CLOSED, OTHER)
DOOR_STATE_ALARMS = (FORCED_OPEN, HELD_OPEN)

# Ordered most-specific first: "remote_unlock" must resolve to a command rather
# than to the generic "unlock" grant token.
_TYPE_TOKENS = (
    (FORCED_OPEN, ("forced_open", "force_open", "forcedopen", "door_forced", "forced_entry", "forced")),
    (HELD_OPEN, ("held_open", "hold_open", "heldopen", "door_held", "open_too_long", "held")),
    (DOORBELL, ("doorbell", "door_bell", "ring", "access_request", "call_request", "intercom")),
    (UNLOCK_COMMAND, ("remote_unlock", "unlock_command", "manual_unlock", "api_unlock", "unlock_request")),
    (DENIED, ("denied", "deny", "reject", "not_authorized", "unauthorized", "invalid", "failed", "blocked")),
    (GRANTED, ("granted", "grant", "authorized", "access_ok", "success", "unlock", "opened", "open")),
    (DOOR_CLOSED, ("closed", "close", "relock", "locked", "lock")),
)

_RESULT_TOKENS = (
    (DENIED, ("denied", "deny", "reject", "blocked", "fail", "unauthorized", "invalid", "false")),
    (GRANTED, ("granted", "grant", "allow", "success", "authorized", "ok", "true")),
)

_METHOD_TOKENS = (
    ("mobile", ("mobile", "bluetooth", "ble", "wallet", "apple", "app")),
    ("nfc", ("nfc", "card", "badge", "fob", "credential_card")),
    ("pin", ("pin", "keypad", "code", "passcode")),
    ("qr", ("qr", "barcode")),
    ("remote", ("remote", "api", "manual", "operator", "web")),
    ("touch", ("touch", "rex", "request_to_exit", "button", "push")),
    ("wave", ("wave", "gesture", "hand")),
)

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_SEEN_LIMIT = 2048
_MILLISECOND_THRESHOLD = 1e11
_STORE_LOCK = threading.RLock()


def _text(event: dict, keys) -> str:
    return " ".join(str(event.get(key) or "") for key in keys).casefold()


def _match(table, text: str) -> str | None:
    for kind, tokens in table:
        if any(token in text for token in tokens):
            return kind
    return None


def classify(event) -> str:
    """Return the normalized kind the Access controller reported.

    `credential_granted` is the canonical flag the Access poller sets from an
    explicitly named grant event. When it is present it decides the grant
    question outright: token matching never upgrades an event the controller
    did not call a credential grant.
    """
    if not isinstance(event, dict):
        return OTHER
    kind = _match(_TYPE_TOKENS, _text(event, ("type", "event_type", "sub_type", "topic", "tag")))
    if kind in (FORCED_OPEN, HELD_OPEN, DOORBELL, UNLOCK_COMMAND, DOOR_CLOSED):
        return kind
    canonical = event.get("credential_granted")
    if canonical is True:
        return GRANTED
    result = _match(_RESULT_TOKENS, _text(event, ("result", "access_result", "authentication_result", "status")))
    resolved = result if result is not None else (kind or OTHER)
    if canonical is False and resolved == GRANTED:
        return OTHER
    return resolved


def method_of(event) -> str:
    """Return the credential method Access reported, or 'unknown'."""
    if not isinstance(event, dict):
        return "unknown"
    text = _text(event, ("method", "credential_type", "auth_type", "authentication", "source", "type"))
    return _match(_METHOD_TOKENS, text) or "unknown"


def event_seconds(event) -> float:
    """Return the event timestamp in epoch seconds (Access reports milliseconds)."""
    if not isinstance(event, dict):
        return 0.0
    for key in ("ts", "event_time", "timestamp", "time"):
        raw = event.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        return value / 1000.0 if value >= _MILLISECOND_THRESHOLD else value
    return 0.0


def door_id_of(event) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("door_id") or (event.get("door") or {}).get("id") or "")


def door_name_of(event) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("door_name") or (event.get("door") or {}).get("name") or "")


def actor_of(event) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("user") or event.get("actor_name") or (event.get("actor") or {}).get("name") or "")


def event_id(event) -> str:
    """Return a stable identifier, synthesizing one when Access omits it."""
    if not isinstance(event, dict):
        return ""
    for key in ("id", "event_id", "_id", "uuid"):
        value = event.get(key)
        if value:
            return str(value)
    return f"{door_id_of(event)}:{event.get('ts')}:{classify(event)}"


def matches_door(event, door_id) -> bool:
    """An unset door_id accepts every door, for single-door deployments."""
    if not door_id:
        return True
    wanted = str(door_id)
    return wanted in (door_id_of(event), door_name_of(event))


def describe(event, *, include_actor: bool = False) -> dict:
    """Alert metadata for one Access event; the actor name stays opt-in."""
    summary = {
        "access_event_id": event_id(event),
        "door_id": door_id_of(event),
        "door_name": door_name_of(event),
        "kind": classify(event),
        "method": method_of(event),
        "event_seconds": round(event_seconds(event), 3),
    }
    if include_actor:
        summary["actor"] = actor_of(event)
    return summary


class AccessEventFeed:
    """Deduplicated, door-scoped, time-windowed view of ctx.access_events."""

    def __init__(self, door_id=None, kinds=None, *, skew_seconds: float = 5.0, max_seen: int = _SEEN_LIMIT):
        self.door_id = door_id
        self.kinds = frozenset(kinds) if kinds else None
        self.skew_seconds = max(0.0, float(skew_seconds))
        self.max_seen = max(16, int(max_seen))
        self._seen = OrderedDict()

    def poll(self, ctx, now: float, window: float) -> list[tuple[float, str, dict]]:
        """Return `(seconds, kind, event)` for events first seen in this window."""
        buffer = getattr(ctx, "access_events", None) or ()
        horizon = max(0.0, float(window))
        fresh = []
        for event in list(buffer):
            if not isinstance(event, dict) or not matches_door(event, self.door_id):
                continue
            seconds = event_seconds(event)
            if seconds <= 0 or not -self.skew_seconds <= now - seconds <= horizon:
                continue
            kind = classify(event)
            if self.kinds is not None and kind not in self.kinds:
                continue
            identifier = event_id(event)
            if identifier in self._seen:
                continue
            self._seen[identifier] = seconds
            fresh.append((seconds, kind, event))
        while len(self._seen) > self.max_seen:
            self._seen.popitem(last=False)
        fresh.sort(key=lambda item: (item[0], item[1]))
        return fresh


def safe_component(value: str, *, fallback: str = "event") -> str:
    """Filesystem-safe, collision-resistant component for an Access identifier."""
    raw = str(value)
    slug = _SAFE_COMPONENT.sub("_", raw).strip("._-")[:64] or fallback
    return f"{slug}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def data_directory(name: str) -> Path:
    """Return a bounded, created subdirectory of VISION_DATA for local records."""
    root = Path(os.environ.get("VISION_DATA", "/app/data")).resolve()
    directory = (root / name).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("access record directory must remain inside VISION_DATA")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def append_record(directory: Path, filename: str, record: dict, *, max_records: int) -> None:
    """Append one JSON line and trim the file to the newest max_records lines."""
    path = Path(directory) / filename
    limit = max(1, int(max_records))
    line = json.dumps(record, separators=(",", ":"), sort_keys=True, default=str)
    with _STORE_LOCK:
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            existing = []
        existing = [item for item in existing if item.strip()]
        existing.append(line)
        payload = "\n".join(existing[-limit:]) + "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)


def read_records(directory: Path, filename: str) -> list[dict]:
    """Read the local JSON-lines record file, skipping unreadable lines."""
    path = Path(directory) / filename
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def write_package(directory: Path, name: str, package: dict) -> Path:
    """Write one JSON package file atomically and return its path."""
    path = Path(directory) / f"{name}.json"
    payload = json.dumps(package, indent=1, sort_keys=True, default=str) + "\n"
    with _STORE_LOCK:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    return path


def prune_files(directory: Path, pattern: str, *, max_files: int, retention_days: float, now=None) -> None:
    """Bound a local record directory by age and by file count."""
    current = time.time() if now is None else float(now)
    root = Path(directory)
    with _STORE_LOCK:
        files = sorted(
            (path for path in root.glob(pattern) if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if float(retention_days) > 0:
            cutoff = current - float(retention_days) * 86400
            for path in list(files):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            files = [path for path in files if path.exists()]
        for path in files[max(1, int(max_files)):]:
            path.unlink(missing_ok=True)
