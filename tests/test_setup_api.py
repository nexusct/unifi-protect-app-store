from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient
import pydantic.networks as pydantic_networks


def _test_validate_email(value, **_kwargs):
    text = str(value)
    return SimpleNamespace(normalized=text, local_part=text.partition("@")[0])


setattr(pydantic_networks, "email_validator", SimpleNamespace(validate_email=_test_validate_email))
setattr(pydantic_networks, "import_email_validator", lambda: None)


class _Response:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ProtectClientContractTests(unittest.TestCase):
    def test_explicit_connection_discovers_lowest_enabled_secure_rtsp_feed(self):
        from unifi_protect import ProtectClient

        session = Mock()
        session.headers = {}
        session.post.return_value = _Response(headers={"x-csrf-token": "csrf"})
        session.get.return_value = _Response(
            [
                {
                    "id": "camera-one",
                    "name": "North Entry",
                    "type": "UVC G5 Bullet",
                    "state": "CONNECTED",
                    "channels": [
                        {
                            "rtspAlias": "high",
                            "isRtspEnabled": True,
                            "width": 3840,
                            "height": 2160,
                            "fps": 30,
                        },
                        {
                            "rtspAlias": "low",
                            "isRtspEnabled": True,
                            "width": 1280,
                            "height": 720,
                            "fps": 15,
                        },
                    ],
                }
            ]
        )
        client = ProtectClient(
            host="192.168.10.1",
            port=443,
            username="vision-service",
            password="secret-value",
            verify=True,
            session=session,
        )
        cameras = client.cameras()
        self.assertEqual(session.verify, True)
        session.post.assert_called_once_with(
            "https://192.168.10.1:443/api/auth/login",
            json={"username": "vision-service", "password": "secret-value"},
            timeout=15,
        )
        self.assertEqual(
            cameras,
            [
                {
                    "id": "camera-one",
                    "name": "North Entry",
                    "model": "UVC G5 Bullet",
                    "state": "CONNECTED",
                    "rtsp": "rtsps://192.168.10.1:7441/low",
                    "rtsp_enabled": True,
                    "stream": {"width": 1280, "height": 720, "fps": 15},
                }
            ],
        )


class SetupServiceContractTests(unittest.TestCase):
    def _service(self, root: Path, cameras, certificate=None):
        from setup_service import SetupService, SetupStore

        factory = Mock()
        factory.return_value.cameras.return_value = cameras
        fetcher = Mock(return_value=certificate) if certificate is not None else Mock()
        store = SetupStore(root / "sites.yaml", root / "runtime-settings.json", root / "certs")
        return SetupService(store, protect_client_factory=factory, certificate_fetcher=fetcher), factory, fetcher

    def test_discovery_returns_only_canonical_camera_fields_and_no_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, factory, _fetcher = self._service(
                root,
                [
                    {
                        "id": "camera-one",
                        "name": "North Entry",
                        "model": "G5 Bullet",
                        "state": "CONNECTED",
                        "rtsp": "rtsps://nvr.local:7441/low",
                        "rtsp_enabled": True,
                        "stream": {"width": 1280, "height": 720, "fps": 15},
                        "ignored_raw": "must-not-cross-setup-seam",
                    }
                ],
            )
            result = service.discover(
                {
                    "host": "nvr.local",
                    "port": 443,
                    "username": "service-account",
                    "password": "do-not-echo",
                    "tls_mode": "system",
                }
            )
            serialized = json.dumps(result)
            self.assertNotIn("do-not-echo", serialized)
            self.assertNotIn("service-account", serialized)
            self.assertNotIn("ignored_raw", serialized)
            self.assertEqual(result["camera_count"], 1)
            self.assertTrue(result["cameras"][0]["rtsp_enabled"])
            self.assertEqual(factory.call_args.kwargs["verify"], True)

    def test_pinned_certificate_must_match_then_becomes_the_requests_ca_file(self):
        fingerprint = "ab" * 32
        certificate = {"pem": "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n", "sha256": fingerprint}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, factory, fetcher = self._service(
                root,
                [
                    {
                        "id": "camera-one",
                        "name": "Entry",
                        "model": "Camera",
                        "state": "CONNECTED",
                        "rtsp": "rtsps://192.168.20.1:7441/low",
                        "rtsp_enabled": True,
                        "stream": {"width": 1280, "height": 720, "fps": 15},
                    }
                ],
                certificate,
            )
            inspected = service.inspect_certificate("192.168.20.1", 443)
            self.assertEqual(inspected, {"sha256": fingerprint, "display_sha256": ":".join(["AB"] * 32)})
            result = service.configure(
                site_name="Site",
                timezone_name="UTC",
                connection={
                    "host": "192.168.20.1",
                    "port": 443,
                    "username": "service",
                    "password": "secret",
                    "tls_mode": "pinned",
                    "certificate_sha256": fingerprint.upper(),
                },
                selected_camera_ids=["camera-one"],
                detectors_by_camera={"camera-one": ["camera-tamper"]},
            )
            self.assertTrue(result["saved"])
            verify_path = Path(factory.call_args.kwargs["verify"])
            self.assertTrue(verify_path.is_file())
            self.assertEqual(verify_path.read_text(encoding="utf-8"), certificate["pem"])
            settings = json.loads((root / "runtime-settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["UNIFI_PROTECT_VERIFY_SSL"], str(verify_path))
            fetcher.assert_called()

    def test_configure_re_discovers_and_rejects_unknown_camera_selection(self):
        from setup_service import SetupValidationError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _factory, _fetcher = self._service(root, [])
            with self.assertRaises(SetupValidationError):
                service.configure(
                    site_name="Site",
                    timezone_name="UTC",
                    connection={
                        "host": "nvr.local",
                        "port": 443,
                        "username": "service",
                        "password": "secret",
                        "tls_mode": "system",
                    },
                    selected_camera_ids=["not-discovered"],
                    detectors_by_camera={},
                )


class SetupApiContractTests(unittest.TestCase):
    def _client(self, service, restart_callback=None):
        import api

        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        previous_token = os.environ.get("VISION_ADMIN_TOKEN")
        os.environ["VISION_ADMIN_TOKEN"] = "a-valid-random-admin-token"

        def restore_token():
            if previous_token is None:
                os.environ.pop("VISION_ADMIN_TOKEN", None)
            else:
                os.environ["VISION_ADMIN_TOKEN"] = previous_token

        self.addCleanup(restore_token)
        with patch("subscriptions.store.init_db", return_value=None):
            app = api.create_app(
                pipeline,
                streams,
                setup_service=service,
                restart_callback=restart_callback,
            )
        return TestClient(app)

    def test_setup_routes_require_admin_token_and_never_echo_passwords(self):
        service = Mock()
        service.discover.return_value = {"connected": True, "camera_count": 0, "cameras": []}
        client = self._client(service)
        payload = {
            "host": "nvr.local",
            "port": 443,
            "username": "service",
            "password": "super-secret-password",
            "tls_mode": "system",
        }
        self.assertEqual(client.post("/api/setup/protect/discover", json=payload).status_code, 401)
        response = client.post(
            "/api/setup/protect/discover",
            json=payload,
            headers={"x-admin-token": "a-valid-random-admin-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("super-secret-password", response.text)
        service.discover.assert_called_once()

        malformed = dict(payload, port=70000)
        response = client.post(
            "/api/setup/protect/discover",
            json=malformed,
            headers={"x-admin-token": "a-valid-random-admin-token"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("super-secret-password", response.text)

    def test_restart_is_admin_gated_and_requires_saved_configuration(self):
        service = Mock()
        service.status.side_effect = [
            {"configured": False, "camera_count": 0},
            {"configured": True, "camera_count": 1},
        ]
        restarted = Mock()
        client = self._client(service, restart_callback=restarted)
        headers = {"x-admin-token": "a-valid-random-admin-token"}
        self.assertEqual(client.post("/api/setup/restart", headers=headers).status_code, 409)
        self.assertEqual(client.post("/api/setup/restart", headers=headers).status_code, 202)
        restarted.assert_called_once()


if __name__ == "__main__":
    unittest.main()
