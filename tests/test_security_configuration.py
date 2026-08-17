from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from site_time import require_site_timezone
from subscriptions import store
from tls_verify import tls_verify_from_env


class SecurityConfigurationTests(unittest.TestCase):
    def test_tls_verification_defaults_on_and_supports_explicit_ca_bundle(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(tls_verify_from_env("TEST_VERIFY_SSL"), True)
        with patch.dict(os.environ, {"TEST_VERIFY_SSL": "false"}, clear=True):
            self.assertIs(tls_verify_from_env("TEST_VERIFY_SSL"), False)
        with patch.dict(os.environ, {"TEST_VERIFY_SSL": "/run/secrets/controller-ca.pem"}, clear=True):
            self.assertEqual(
                tls_verify_from_env("TEST_VERIFY_SSL"),
                "/run/secrets/controller-ca.pem",
            )

    def test_subscription_ids_do_not_collide_within_the_same_second(self):
        request = {
            "company": "Example Company",
            "contactName": "Example Contact",
            "email": "contact@example.invalid",
            "tier": "starter",
            "functions": ["wrong-way"],
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            store, "DB_PATH", Path(temporary) / "subscriptions.db"
        ), patch("subscriptions.store.time.time", return_value=1_800_000_000):
            store.init_db()
            first = store.create_sub(request)
            second = store.create_sub(request)

        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(first["id"].startswith("SUB-"))
        self.assertGreaterEqual(len(first["id"]), 32)

    def test_base44_forwarding_requires_both_url_and_non_placeholder_token(self):
        row = {
            "id": "SUB-test",
            "company": "Example",
            "contact_name": "Contact",
            "email": "contact@example.invalid",
            "phone": "",
            "industry": "",
            "sites": 1,
            "cameras": None,
            "functions": "[]",
            "tier": "starter",
        }
        with patch.dict(
            os.environ,
            {"BASE44_ALERT_URL": "https://example.invalid/ingest", "BASE44_INTERNAL_TOKEN": ""},
            clear=False,
        ), patch("requests.post") as post:
            self.assertFalse(store.forward_to_base44(row))
        post.assert_not_called()

    def test_site_timezone_is_required_and_must_be_an_iana_name(self):
        with self.assertRaisesRegex(ValueError, "site.timezone is required"):
            require_site_timezone({"site": {"name": "Missing Zone"}})
        with self.assertRaisesRegex(ValueError, "not a recognized IANA timezone"):
            require_site_timezone({"site": {"timezone": "Chicago-ish"}})
        timezone = require_site_timezone({"site": {"timezone": "America/Chicago"}})
        self.assertEqual(timezone.key, "America/Chicago")

    def test_subscription_status_source_is_admin_gated(self):
        source = (SRC / "subscriptions" / "app.py").read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"def status\(sub_id: str, x_admin_token: str \| None = Header\(default=None\)\):\s+_admin_ok\(x_admin_token\)",
        )
        environment = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("VISION_ADMIN_TOKEN=change-me-before-enabling-admin-api", environment)

    def test_container_inputs_are_immutable_and_packaging_toolchain_is_patched(self):
        for filename in ("requirements.txt", "requirements.lock"):
            path = ROOT / filename
            self.assertTrue(path.is_file(), filename)
            requirements = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            mutable = [line for line in requirements if "==" not in line]
            self.assertEqual(mutable, [], f"mutable requirements in {filename}")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("wheel==0.48.0", requirements)
        self.assertIn("setuptools==84.0.0", requirements)
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04@sha256:"
            "f4d8e1264366940438f0353da6f289c7bef069d993d111f8106086ccd18c4a30",
            dockerfile,
        )
        self.assertIn('"pip==26.2.1"', dockerfile)
        self.assertIn('"setuptools==84.0.0"', dockerfile)
        self.assertIn("python -m pip install -r requirements.lock", dockerfile)

    def test_container_context_excludes_local_review_workspace(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".hallmark/", dockerignore)

    def test_container_makes_public_static_trees_readable_by_runtime_user(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "chmod -R a+rX /app/assets /app/landing /app/storefront /app/guide /app/setup",
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
