"""UniFi Access API client: door events (badge/open/forced) for correlation."""
import logging
import os
import threading
import time

import requests

from tls_verify import tls_verify_from_env

log = logging.getLogger("unifi_access")

_CREDENTIAL_GRANT_EVENT_TYPES = {
    "access_granted",
    "credential_granted",
    "door_access_granted",
}


def _normalized_event_type(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_explicit_credential_grant(event: dict) -> bool:
    """Accept only a canonical flag or an explicitly named grant event."""
    canonical = event.get("credential_granted")
    if isinstance(canonical, bool):
        return canonical
    return _normalized_event_type(event.get("event_type") or event.get("type")) in _CREDENTIAL_GRANT_EVENT_TYPES


class AccessPoller:
    """Polls the local Access API for door log events and fans them out to
    subscribers (tailgating detector, alert correlation)."""

    def __init__(self, on_event, *, capability_authorizer=None):
        self.host = os.environ.get("UNIFI_ACCESS_HOST", "")
        self.token = os.environ.get("UNIFI_ACCESS_TOKEN", "")
        self.verify = tls_verify_from_env("UNIFI_ACCESS_VERIFY_SSL")
        self.on_event = on_event
        self.capability_authorizer = capability_authorizer
        self.enabled = bool(self.host and self.token)
        self._stop = threading.Event()
        self._thread = None
        self._last_seen = int(time.time() * 1000)

    @property
    def base(self):
        return f"https://{self.host}/proxy/access/api/v1"

    def start(self):
        if not self.enabled:
            log.info("Access poller disabled (no host/token) — tailgating runs in degraded mode")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="access-poller")
        self._thread.start()
        log.info("Access poller started (%s)", self.host)

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                events = self._poll_once()
                for ev in events:
                    self.on_event(ev)
            except Exception as exc:
                log.warning("Access poll error: %s", exc)
            self._stop.wait(2.0)

    def _poll_once(self):
        r = requests.get(
            f"{self.base}/developer/logs",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            params={"since": self._last_seen},
            verify=self.verify,
            timeout=15,
        )
        if r.status_code != 200:
            log.warning("Access logs %s", r.status_code)
            return []
        data = r.json()
        hits = data.get("hits", data if isinstance(data, list) else [])
        events = [self._normalize(h) for h in hits]
        for event in events:
            try:
                stamp = int(event["ts"])
            except (TypeError, ValueError):
                continue
            if stamp > self._last_seen:
                self._last_seen = stamp
        return events

    @staticmethod
    def _normalize(hit: dict) -> dict:
        """Flatten one Access log hit into the shared correlation vocabulary."""
        door = hit.get("door") or {}
        actor = hit.get("actor") or {}
        authentication = hit.get("authentication") or {}
        ts = hit.get("event_time") or hit.get("timestamp") or 0
        event = {
            "id": hit.get("_id") or hit.get("id") or hit.get("event_id") or "",
            "ts": ts,
            "door_id": door.get("id") or hit.get("door_id"),
            "door_name": door.get("name") or hit.get("door_name"),
            "type": hit.get("event_type") or hit.get("type", ""),
            "result": hit.get("result") or hit.get("access_result") or authentication.get("result") or "",
            "method": (
                authentication.get("credential_provider")
                or hit.get("credential_type")
                or hit.get("auth_type")
                or ""
            ),
            "user": actor.get("name") or hit.get("user", ""),
            "actor_id": actor.get("id") or hit.get("actor_id") or "",
        }
        event["credential_granted"] = is_explicit_credential_grant(event)
        return event

    def unlock(self, door_id: str) -> bool:
        """Remote unlock, fail-closed beneath every caller without capability."""
        if self.capability_authorizer is None:
            return False
        try:
            if not self.capability_authorizer("access-control"):
                return False
            r = requests.put(
                f"{self.base}/developer/doors/{door_id}/unlock",
                headers={"Authorization": f"Bearer {self.token}"},
                verify=self.verify,
                timeout=10,
            )
            return r.status_code == 200
        except Exception as exc:
            log.warning("unlock failed: %s", exc)
            return False
