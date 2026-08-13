"""UniFi Access API client: door events (badge/open/forced) for correlation."""
import logging
import os
import threading
import time

import requests

log = logging.getLogger("unifi_access")


class AccessPoller:
    """Polls the local Access API for door log events and fans them out to
    subscribers (tailgating detector, alert correlation)."""

    def __init__(self, on_event):
        self.host = os.environ.get("UNIFI_ACCESS_HOST", "")
        self.token = os.environ.get("UNIFI_ACCESS_TOKEN", "")
        self.verify = os.environ.get("UNIFI_ACCESS_VERIFY_SSL", "false").lower() == "true"
        self.on_event = on_event
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
        events = []
        for h in hits:
            ts = h.get("event_time") or h.get("timestamp") or 0
            events.append(
                {
                    "ts": ts,
                    "door_id": (h.get("door") or {}).get("id") or h.get("door_id"),
                    "door_name": (h.get("door") or {}).get("name") or h.get("door_name"),
                    "type": h.get("event_type") or h.get("type", ""),
                    "user": (h.get("actor") or {}).get("name") or h.get("user", ""),
                }
            )
            if ts > self._last_seen:
                self._last_seen = ts
        return events

    def unlock(self, door_id: str) -> bool:
        """Remote unlock (used by intercom-verified delivery flows)."""
        try:
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
