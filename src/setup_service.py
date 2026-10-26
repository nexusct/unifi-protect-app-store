"""Validated, atomic persistence for first-run UniFi onboarding."""
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import ssl
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from unifi_protect import ProtectClient

CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DETECTOR_ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\]|[0-9A-Fa-f:]+)$")


class SetupValidationError(ValueError):
    """A setup value is unsafe or cannot be represented by the runtime."""


def _text(value: Any, field: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or any(ord(character) < 32 for character in result):
        raise SetupValidationError(f"invalid {field}")
    return result


def validate_host(value: Any) -> str:
    host = _text(value, "UniFi host", 253)
    if "://" in host or "/" in host or "@" in host or not HOST_RE.fullmatch(host):
        raise SetupValidationError("UniFi host must be a hostname or IP address without a URL path")
    return host


def _validated_rtsp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    result = _text(value, "RTSP URL", 2048)
    parsed = urlsplit(result)
    if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname or parsed.username or parsed.password:
        raise SetupValidationError("RTSP URL must use rtsp/rtsps and must not embed credentials")
    return result


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class SetupStore:
    """Own the secret/settings and site-config persistence seam."""

    def __init__(self, config_path: str | Path, settings_path: str | Path, certs_path: str | Path):
        self.config_path = Path(config_path)
        self.settings_path = Path(settings_path)
        self.certs_path = Path(certs_path)

    def save(
        self,
        *,
        site_name: Any,
        timezone_name: Any,
        connection: dict[str, Any],
        cameras: list[dict[str, Any]],
    ) -> dict[str, Any]:
        name = _text(site_name, "site name", 100)
        timezone = _text(timezone_name, "site timezone", 100)
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise SetupValidationError("site timezone must be a recognized IANA timezone") from exc

        host = validate_host(connection.get("host"))
        try:
            port = int(connection.get("port", 443))
        except (TypeError, ValueError) as exc:
            raise SetupValidationError("invalid UniFi port") from exc
        if not 1 <= port <= 65535:
            raise SetupValidationError("invalid UniFi port")
        username = _text(connection.get("username"), "UniFi username", 256)
        password = _text(connection.get("password"), "UniFi password", 4096)
        tls_mode = str(connection.get("tls_mode", "system")).strip().lower()
        if tls_mode not in {"system", "pinned", "custom_ca"}:
            raise SetupValidationError("unsupported TLS mode")
        if tls_mode == "system":
            verify_value = "true"
        else:
            verify_path = Path(str(connection.get("verify") or "")).resolve()
            cert_root = self.certs_path.resolve()
            try:
                verify_path.relative_to(cert_root)
            except ValueError as exc:
                raise SetupValidationError("controller CA path must be inside the setup certificate directory") from exc
            if not verify_path.is_file():
                raise SetupValidationError("controller CA file does not exist")
            verify_value = str(verify_path)

        normalized_cameras = []
        seen_ids = set()
        for camera in cameras:
            camera_id = _text(camera.get("id"), "camera identifier", 128)
            if not CAMERA_ID_RE.fullmatch(camera_id) or camera_id in seen_ids:
                raise SetupValidationError("invalid or duplicate camera identifier")
            seen_ids.add(camera_id)
            detector_ids = []
            for detector in camera.get("detectors") or []:
                detector_id = _text(detector, "detector identifier", 80)
                if not DETECTOR_ID_RE.fullmatch(detector_id) or detector_id in detector_ids:
                    raise SetupValidationError("invalid or duplicate detector identifier")
                detector_ids.append(detector_id)
            normalized_cameras.append(
                {
                    "id": camera_id,
                    "name": _text(camera.get("name"), "camera name", 160),
                    "rtsp": _validated_rtsp(camera.get("rtsp")),
                    "detectors": detector_ids,
                    "zones": {},
                    "privacy_mode": "standard",
                }
            )

        settings = {
            "UNIFI_PROTECT_HOST": host,
            "UNIFI_PROTECT_PORT": str(port),
            "UNIFI_PROTECT_USERNAME": username,
            "UNIFI_PROTECT_PASSWORD": password,
            "UNIFI_PROTECT_VERIFY_SSL": verify_value,
        }
        site_config = {
            "site": {"name": name, "timezone": timezone},
            "cameras": normalized_cameras,
            "detector_settings": {},
            "alerts": {"dedup_seconds": 120, "severities": {}},
        }
        _atomic_write(self.settings_path, json.dumps(settings, indent=2, sort_keys=True) + "\n")
        _atomic_write(self.config_path, yaml.safe_dump(site_config, sort_keys=False))
        return {"saved": True, "camera_count": len(normalized_cameras), "restart_required": True}


def fetch_server_certificate(host: str, port: int) -> dict[str, str]:
    """Read a presented TLS certificate for explicit human fingerprint review."""
    pem = ssl.get_server_certificate((host.strip("[]"), port), timeout=10)
    der = ssl.PEM_cert_to_DER_cert(pem)
    return {"pem": pem, "sha256": hashlib.sha256(der).hexdigest()}


def _fingerprint(value: Any) -> str:
    normalized = re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).lower()
    if len(normalized) != 64:
        raise SetupValidationError("certificate SHA-256 fingerprint must contain 64 hexadecimal characters")
    return normalized


class SetupService:
    """Deep setup module: validate, verify TLS, discover, select, and persist."""

    def __init__(
        self,
        store: SetupStore,
        *,
        protect_client_factory=ProtectClient,
        certificate_fetcher=fetch_server_certificate,
        allowed_detectors: set[str] | None = None,
        configuration_validator: Callable[[dict[str, Any]], Any] | None = None,
    ):
        self.store = store
        self.protect_client_factory = protect_client_factory
        self.certificate_fetcher = certificate_fetcher
        self.allowed_detectors = allowed_detectors
        self.configuration_validator = configuration_validator

    @staticmethod
    def _connection(connection: dict[str, Any]) -> dict[str, Any]:
        host = validate_host(connection.get("host"))
        try:
            port = int(connection.get("port", 443))
        except (TypeError, ValueError) as exc:
            raise SetupValidationError("invalid UniFi port") from exc
        if not 1 <= port <= 65535:
            raise SetupValidationError("invalid UniFi port")
        result = {
            "host": host,
            "port": port,
            "username": _text(connection.get("username"), "UniFi username", 256),
            "password": _text(connection.get("password"), "UniFi password", 4096),
            "tls_mode": str(connection.get("tls_mode", "system")).strip().lower(),
        }
        if result["tls_mode"] not in {"system", "pinned", "custom_ca"}:
            raise SetupValidationError("unsupported TLS mode")
        if result["tls_mode"] == "pinned":
            result["certificate_sha256"] = _fingerprint(connection.get("certificate_sha256"))
        elif result["tls_mode"] == "custom_ca":
            result["ca_bundle"] = _text(connection.get("ca_bundle"), "controller CA path", 1024)
        return result

    def inspect_certificate(self, host: Any, port: Any = 443) -> dict[str, str]:
        validated = validate_host(host)
        try:
            validated_port = int(port)
        except (TypeError, ValueError) as exc:
            raise SetupValidationError("invalid UniFi port") from exc
        if not 1 <= validated_port <= 65535:
            raise SetupValidationError("invalid UniFi port")
        certificate = self.certificate_fetcher(validated, validated_port)
        fingerprint = _fingerprint(certificate.get("sha256"))
        display = ":".join(fingerprint[index:index + 2].upper() for index in range(0, 64, 2))
        return {"sha256": fingerprint, "display_sha256": display}

    def _tls_verify(self, connection: dict[str, Any]) -> bool | str:
        mode = connection["tls_mode"]
        if mode == "system":
            return True
        if mode == "custom_ca":
            path = Path(connection["ca_bundle"]).resolve()
            cert_root = self.store.certs_path.resolve()
            try:
                path.relative_to(cert_root)
            except ValueError as exc:
                raise SetupValidationError("controller CA path must be inside the setup certificate directory") from exc
            if not path.is_file():
                raise SetupValidationError("controller CA file does not exist")
            return str(path)

        certificate = self.certificate_fetcher(connection["host"], connection["port"])
        observed = _fingerprint(certificate.get("sha256"))
        if not secrets.compare_digest(observed, connection["certificate_sha256"]):
            raise SetupValidationError("controller certificate changed or does not match the reviewed fingerprint")
        path = self.store.certs_path / "unifi-protect-pinned.pem"
        pem = str(certificate.get("pem") or "")
        if (
            len(pem) > 64 * 1024
            or not pem.startswith("-----BEGIN CERTIFICATE-----")
            or "-----END CERTIFICATE-----" not in pem
        ):
            raise SetupValidationError("controller returned an invalid certificate")
        _atomic_write(path, pem if pem.endswith("\n") else pem + "\n")
        return str(path.resolve())

    @staticmethod
    def _canonical_camera(camera: dict[str, Any]) -> dict[str, Any]:
        camera_id = _text(camera.get("id"), "camera identifier", 128)
        if not CAMERA_ID_RE.fullmatch(camera_id):
            raise SetupValidationError("Protect returned an invalid camera identifier")
        stream = camera.get("stream") if isinstance(camera.get("stream"), dict) else {}
        return {
            "id": camera_id,
            "name": _text(camera.get("name"), "camera name", 160),
            "model": _text(camera.get("model") or "UniFi camera", "camera model", 160),
            "state": _text(camera.get("state") or "UNKNOWN", "camera state", 64),
            "rtsp": _validated_rtsp(camera.get("rtsp")),
            "rtsp_enabled": bool(camera.get("rtsp_enabled") and camera.get("rtsp")),
            "stream": {
                "width": max(0, min(int(stream.get("width") or 0), 16384)),
                "height": max(0, min(int(stream.get("height") or 0), 16384)),
                "fps": max(0, min(int(stream.get("fps") or 0), 240)),
            },
        }

    def _discover(self, connection: dict[str, Any], verify: bool | str) -> list[dict[str, Any]]:
        client = self.protect_client_factory(
            host=connection["host"],
            port=connection["port"],
            username=connection["username"],
            password=connection["password"],
            verify=verify,
        )
        cameras = [self._canonical_camera(camera) for camera in client.cameras()]
        identifiers = [camera["id"] for camera in cameras]
        if len(identifiers) != len(set(identifiers)):
            raise SetupValidationError("Protect returned duplicate camera identifiers")
        return cameras

    def discover(self, connection: dict[str, Any]) -> dict[str, Any]:
        validated = self._connection(connection)
        cameras = self._discover(validated, self._tls_verify(validated))
        return {"connected": True, "camera_count": len(cameras), "cameras": cameras}

    def configure(
        self,
        *,
        site_name: Any,
        timezone_name: Any,
        connection: dict[str, Any],
        selected_camera_ids: list[Any],
        detectors_by_camera: dict[str, list[Any]],
    ) -> dict[str, Any]:
        validated = self._connection(connection)
        verify = self._tls_verify(validated)
        discovered = {camera["id"]: camera for camera in self._discover(validated, verify)}
        selected = []
        seen = set()
        for raw_camera_id in selected_camera_ids:
            camera_id = _text(raw_camera_id, "selected camera identifier", 128)
            if camera_id in seen or camera_id not in discovered:
                raise SetupValidationError("selected camera was not returned by Protect")
            seen.add(camera_id)
            camera = discovered[camera_id]
            if not camera["rtsp_enabled"]:
                raise SetupValidationError("selected camera does not have an enabled Protect RTSP stream")
            detectors = list(detectors_by_camera.get(camera_id) or [])
            if self.allowed_detectors is not None and not set(detectors).issubset(self.allowed_detectors):
                raise SetupValidationError("selected detector is not installed")
            selected.append({**camera, "detectors": detectors})
        unknown_mapping_ids = set(detectors_by_camera).difference(seen)
        if unknown_mapping_ids:
            raise SetupValidationError("detector mapping contains an unknown camera")
        if not selected:
            raise SetupValidationError("select at least one RTSP-enabled camera")
        if self.configuration_validator is not None:
            authorization = self.configuration_validator(
                {
                    "site": {"name": str(site_name or ""), "timezone": str(timezone_name or "")},
                    "cameras": selected,
                    "detector_settings": {},
                    "alerts": {},
                }
            )
            if not getattr(authorization, "authorized", False):
                raise SetupValidationError(
                    "selected functions require a current signed entitlement and must remain within its grants and limits"
                )
        return self.store.save(
            site_name=site_name,
            timezone_name=timezone_name,
            connection={**validated, "verify": verify},
            cameras=selected,
        )

    def status(self) -> dict[str, Any]:
        try:
            config = yaml.safe_load(self.store.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, TypeError):
            config = {}
        cameras = config.get("cameras") if isinstance(config, dict) else []
        if not isinstance(cameras, list):
            cameras = []
        try:
            settings = json.loads(self.store.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            settings = {}
        required = ("UNIFI_PROTECT_HOST", "UNIFI_PROTECT_USERNAME", "UNIFI_PROTECT_PASSWORD")
        configured = bool(cameras) and isinstance(settings, dict) and all(settings.get(key) for key in required)
        return {
            "configured": configured,
            "camera_count": len(cameras),
            "site_name": str((config.get("site") or {}).get("name") or "") if isinstance(config, dict) else "",
            "device": os.environ.get("VISION_DEVICE", "cpu"),
        }
