"""UniFi Protect API client: camera discovery, RTSP mapping, events, clips."""
import logging
import os

import requests

log = logging.getLogger("unifi_protect")


class ProtectClient:
    def __init__(self):
        self.host = os.environ["UNIFI_PROTECT_HOST"]
        self.port = int(os.environ.get("UNIFI_PROTECT_PORT", "443"))
        self.verify = os.environ.get("UNIFI_PROTECT_VERIFY_SSL", "false").lower() == "true"
        self.base = f"https://{self.host}:{self.port}/proxy/protect/api"
        self.session = requests.Session()
        self.session.verify = self.verify
        self.session.headers.update({"Accept": "application/json"})
        self._login()

    def _login(self):
        r = self.session.post(
            f"https://{self.host}:{self.port}/api/auth/login",
            json={
                "username": os.environ["UNIFI_PROTECT_USERNAME"],
                "password": os.environ["UNIFI_PROTECT_PASSWORD"],
            },
            timeout=15,
        )
        r.raise_for_status()
        csrf = r.headers.get("x-csrf-token") or r.headers.get("X-CSRF-Token")
        if csrf:
            self.session.headers.update({"X-CSRF-Token": csrf})
        log.info("Protect login OK (%s)", self.host)

    def cameras(self):
        """Return [{id, name, rtsp_url}] for all cameras."""
        r = self.session.get(f"{self.base}/cameras", timeout=15)
        r.raise_for_status()
        out = []
        for cam in r.json():
            channels = cam.get("channels") or []
            rtsp = None
            for ch in channels:
                if ch.get("rtspAlias") and ch.get("isRtspEnabled"):
                    rtsp = f"rtsps://{self.host}:7441/{ch['rtspAlias']}"
                    break
            out.append({"id": cam.get("id"), "name": cam.get("name"), "rtsp": rtsp})
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

    def download_clip(self, camera_id: str, start_ms: int, end_ms: int, dest: str) -> str | None:
        try:
            with self.session.get(
                self.clip_url(camera_id, start_ms, end_ms), stream=True, timeout=60
            ) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return dest
        except Exception as exc:
            log.warning("clip export failed: %s", exc)
            return None
