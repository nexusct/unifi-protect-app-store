from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from activation.service import ActivationError, ActivationService


class FakeLicenseService:
    def __init__(self, *, authorized: bool = True, reason: str = "authorized"):
        self.authorized = authorized
        self.reason = reason
        self.calls = []

    def validate_configuration(self, config):
        self.calls.append(config)
        return SimpleNamespace(
            authorized=self.authorized,
            reason=self.reason,
            effective_config=config if self.authorized else {"cameras": []},
        )


class ActivationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "config" / "sites.yaml"
        self.now = 1_800_000_000
        self.license = FakeLicenseService()
        self.ready = True
        self.reloads = []
        self.service = ActivationService(
            directory=self.root / "activation",
            config_path=self.config_path,
            license_service=self.license,
            clock=lambda: self.now,
            platform_probe=lambda: ("linux", "x86_64"),
            reload_callback=lambda path: self.reloads.append(Path(path).read_bytes()),
            readiness_check=lambda: self.ready,
        )

    @staticmethod
    def config(detector: str = "alpha", threshold: float = 0.5) -> dict:
        return {
            "site": {"name": "Sensitive local site", "timezone": "UTC"},
            "cameras": [
                {
                    "id": "camera-one",
                    "name": "Private camera name",
                    "rtsp": "rtsps://nvr.invalid/private-stream",
                    "detectors": [detector] if detector else [],
                    "zones": {"door": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]},
                }
            ],
            "detector_settings": {detector: {"threshold": threshold}} if detector else {},
            "alerts": {"dedup_seconds": 120},
        }

    def test_plan_is_opaque_redacted_owner_only_and_rejects_denied_or_wrong_platform(self):
        requested = self.config()
        plan = self.service.plan(requested)

        self.assertEqual(set(plan), {"plan_id", "expires_at", "summary"})
        self.assertGreaterEqual(len(plan["plan_id"]), 32)
        serialized = json.dumps(plan)
        self.assertNotIn("Private camera name", serialized)
        self.assertNotIn("private-stream", serialized)
        self.assertEqual(plan["summary"]["camera_count"], 1)
        self.assertEqual(plan["summary"]["function_ids"], ["alpha"])
        plan_files = list((self.root / "activation" / "plans").glob("*.json"))
        self.assertEqual(len(plan_files), 1)
        self.assertEqual(plan_files[0].stat().st_mode & 0o777, 0o600)

        denied = ActivationService(
            directory=self.root / "denied",
            config_path=self.root / "denied.yaml",
            license_service=FakeLicenseService(authorized=False, reason="expired"),
            clock=lambda: self.now,
            platform_probe=lambda: ("linux", "x86_64"),
        )
        with self.assertRaises(ActivationError) as denied_error:
            denied.plan(requested)
        self.assertEqual(denied_error.exception.code, "expired")

        unsupported = ActivationService(
            directory=self.root / "unsupported",
            config_path=self.root / "unsupported.yaml",
            license_service=self.license,
            clock=lambda: self.now,
            platform_probe=lambda: ("darwin", "arm64"),
        )
        with self.assertRaises(ActivationError) as platform_error:
            unsupported.plan(requested)
        self.assertEqual(platform_error.exception.code, "unsupported_platform")

    def test_apply_is_atomic_single_use_audited_and_retains_last_five_revisions(self):
        results = []
        for index in range(6):
            plan = self.service.plan(self.config(threshold=0.1 + index / 10))
            results.append(self.service.apply(plan["plan_id"]))

        self.assertEqual([result["revision"] for result in results], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(result["applied"] for result in results))
        self.assertEqual(len(self.reloads), 6)
        revisions = sorted((self.root / "activation" / "revisions").glob("*-good.yaml"))
        self.assertEqual(len(revisions), 5)
        self.assertTrue(revisions[0].name.startswith("00000000000000000002-"))
        state = json.loads((self.root / "activation" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["max_revision"], 6)
        self.assertEqual((self.root / "activation" / "state.json").stat().st_mode & 0o777, 0o600)

        audit_text = (self.root / "activation" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertEqual(len(audit_text.splitlines()), 12)
        self.assertNotIn("Private camera name", audit_text)
        self.assertNotIn("private-stream", audit_text)
        self.assertEqual((self.root / "activation" / "audit.jsonl").stat().st_mode & 0o777, 0o600)

        with self.assertRaises(ActivationError) as replay:
            self.service.apply(results[-1]["plan_id"])
        self.assertEqual(replay.exception.code, "plan_missing")

    def test_readiness_failure_restores_previous_config_and_preserves_failed_revision(self):
        initial = self.service.plan(self.config(threshold=0.5))
        self.service.apply(initial["plan_id"])
        previous = self.config_path.read_bytes()

        self.ready = False
        candidate = self.service.plan(self.config(threshold=0.9))
        with self.assertRaises(ActivationError) as failed:
            self.service.apply(candidate["plan_id"])

        self.assertEqual(failed.exception.code, "readiness_failed")
        self.assertEqual(self.config_path.read_bytes(), previous)
        failed_revisions = list((self.root / "activation" / "revisions").glob("*-failed.yaml"))
        self.assertEqual(len(failed_revisions), 1)
        self.assertEqual(len(self.reloads), 3)  # initial, candidate, restored previous
        state = json.loads((self.root / "activation" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["max_revision"], 2)
        self.assertEqual(state["active_revision"], 1)
        with self.assertRaises(ActivationError) as replay:
            self.service.apply(candidate["plan_id"])
        self.assertEqual(replay.exception.code, "plan_missing")


    def test_activation_router_is_admin_protected_strict_and_redacted(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from activation.api import build_activation_router

        def authorize(token):
            if token != "unit-test-admin":
                raise HTTPException(status_code=401, detail="admin required")

        app = FastAPI()
        app.include_router(build_activation_router(self.service, authorize))
        client = TestClient(app)
        requested = self.config()
        self.assertEqual(
            client.post("/api/activation/plan", json={"config": requested}).status_code,
            401,
        )
        headers = {"x-admin-token": "unit-test-admin"}
        unknown = client.post(
            "/api/activation/plan",
            headers=headers,
            json={"config": requested, "unexpected": True},
        )
        self.assertEqual(unknown.status_code, 422)
        planned = client.post(
            "/api/activation/plan", headers=headers, json={"config": requested}
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        self.assertNotIn("Private camera name", planned.text)
        self.assertNotIn("private-stream", planned.text)
        applied = client.post(
            "/api/activation/apply",
            headers=headers,
            json={"plan_id": planned.json()["plan_id"]},
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        status = client.get("/api/activation/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["active_revision"], 1)

    def test_expired_or_tampered_plan_fails_without_touching_configuration(self):
        original = b"site:\n  name: untouched\n"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_bytes(original)
        plan = self.service.plan(self.config(), ttl_seconds=5)
        self.now += 6

        with self.assertRaises(ActivationError) as expired:
            self.service.apply(plan["plan_id"])
        self.assertEqual(expired.exception.code, "plan_expired")
        self.assertEqual(self.config_path.read_bytes(), original)

        fresh = self.service.plan(self.config())
        plan_file = next((self.root / "activation" / "plans").glob("*.json"))
        payload = json.loads(plan_file.read_text(encoding="utf-8"))
        payload["config"]["site"]["name"] = "tampered"
        plan_file.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(plan_file, 0o600)
        with self.assertRaises(ActivationError) as tampered:
            self.service.apply(fresh["plan_id"])
        self.assertEqual(tampered.exception.code, "plan_invalid")
        self.assertEqual(self.config_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
