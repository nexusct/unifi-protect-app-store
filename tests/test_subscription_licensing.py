from __future__ import annotations

import base64
import copy
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.modules.setdefault("cv2", types.ModuleType("cv2"))

import pydantic.networks as pydantic_networks


def _test_validate_email(value, **_kwargs):
    text = str(value)
    return SimpleNamespace(normalized=text, local_part=text.partition("@")[0])


setattr(pydantic_networks, "email_validator", SimpleNamespace(validate_email=_test_validate_email))
setattr(pydantic_networks, "import_email_validator", lambda: None)

from activation import LicenseService, LicenseValidationError, catalog_sha256


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _sign_segments(
    private_key: Ed25519PrivateKey,
    protected: str,
    payload: str,
) -> str:
    signing_input = f"{protected}.{payload}".encode("ascii")
    return f"{protected}.{payload}.{_b64url(private_key.sign(signing_input))}"


def _sign(private_key: Ed25519PrivateKey, claims: dict, *, kid: str = "test-2026") -> str:
    header = {"alg": "EdDSA", "kid": kid, "typ": "NEXUS-ENTITLEMENT"}
    protected = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return _sign_segments(private_key, protected, payload)


def _noncanonical_b64url(segment: str) -> str:
    """Return a different unpadded spelling that decodes to the same bytes."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    for replacement in alphabet:
        candidate = segment[:-1] + replacement
        if candidate == segment:
            continue
        try:
            value = base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4))
        except ValueError:
            continue
        if value == decoded:
            return candidate
    raise AssertionError("segment has no noncanonical base64url spelling")


class SubscriptionLicensingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.signing_key = Ed25519PrivateKey.generate()
        self.now = 1_800_000_000
        self.catalog = [
            {"id": "alpha", "tier": "starter"},
            {"id": "beta", "tier": "starter"},
            {"id": "gamma", "tier": "starter"},
            {"id": "delta", "tier": "starter"},
            {"id": "epsilon", "tier": "starter"},
            {"id": "zeta", "tier": "starter"},
            {"id": "pro-only", "tier": "pro"},
            {"id": "enterprise-only", "tier": "enterprise"},
        ]
        self.catalog_hash = catalog_sha256(self.catalog)
        self.service = LicenseService(
            directory=self.root / "licensing",
            trusted_keys={"test-2026": self.signing_key.public_key()},
            catalog_sha256=self.catalog_hash,
            installed_function_tiers={row["id"]: row["tier"] for row in self.catalog},
            clock=lambda: self.now,
        )
        self.registration = self.service.device_registration()

    def claims(self, **overrides) -> dict:
        values = {
            "schema": "nexus.entitlement/v1",
            "license_id": "lic-current",
            "organization_id": "org-one",
            "site_id": "site-one",
            "device_id": "device-one",
            "device_public_key_sha256": self.registration["public_key_sha256"],
            "plan": "starter",
            "status": "active",
            "limits": {"sites": 1, "streams": 8, "distinct_functions": 5},
            "function_ids": ["alpha", "beta", "gamma", "delta", "epsilon"],
            "capabilities": [],
            "catalog_sha256": self.catalog_hash,
            "revision": 1,
            "issued_at": _timestamp(self.now - 60),
            "not_before": _timestamp(self.now - 60),
            "expires_at": _timestamp(self.now + 3600),
            "grace_until": _timestamp(self.now + 7200),
        }
        values.update(overrides)
        return values

    @staticmethod
    def config(mapping: dict[str, list[str]]) -> dict:
        return {
            "site": {"name": "Local display name", "timezone": "UTC"},
            "cameras": [
                {
                    "id": camera_id,
                    "name": camera_id,
                    "rtsp": f"rtsps://nvr.invalid/{camera_id}",
                    "detectors": list(detectors),
                    "zones": {},
                }
                for camera_id, detectors in mapping.items()
            ],
            "detector_settings": {},
            "alerts": {"dedup_seconds": 120},
        }

    def install(self, claims: dict | None = None, *, kid: str = "test-2026") -> str:
        token = _sign(self.signing_key, claims or self.claims(), kid=kid)
        result = self.service.install_entitlement(token)
        self.assertIn(result["state"], {"current", "grace"})
        return token

    def test_valid_current_entitlement_authorizes_explicit_grants(self):
        token = self.install()
        requested = self.config({"camera-one": ["alpha", "beta"]})

        result = self.service.authorize_configuration(requested)

        self.assertTrue(result.authorized)
        self.assertEqual(result.state, "current")
        self.assertEqual(result.reason, "authorized")
        self.assertEqual(result.stream_count, 1)
        self.assertEqual(result.distinct_function_count, 2)
        self.assertEqual(result.effective_config, requested)
        status = self.service.status()
        self.assertEqual(status["state"], "current")
        self.assertEqual(status["function_grant_count"], 5)
        self.assertNotIn(token, json.dumps(status))
        self.assertNotIn("private", json.dumps(status).lower())

    def test_entitlement_can_grant_complete_100_catalog_plus_10_core_set(self):
        function_ids = [f"function-{index:03d}" for index in range(110)]
        catalog = [{"id": function_id, "tier": "enterprise"} for function_id in function_ids]
        catalog_hash = catalog_sha256(catalog)
        service = LicenseService(
            directory=self.root / "full-catalog-licensing",
            trusted_keys={"test-2026": self.signing_key.public_key()},
            catalog_sha256=catalog_hash,
            installed_function_tiers={function_id: "enterprise" for function_id in function_ids},
            clock=lambda: self.now,
        )
        registration = service.device_registration()
        claims = self.claims(
            license_id="lic-full-catalog",
            plan="enterprise",
            limits={"sites": 1, "streams": 110, "distinct_functions": 110},
            function_ids=function_ids,
            catalog_sha256=catalog_hash,
            device_public_key_sha256=registration["public_key_sha256"],
        )
        installed = service.install_entitlement(_sign(self.signing_key, claims))
        self.assertEqual(installed["function_grant_count"], 110)

    def test_signup_accepts_complete_100_but_rejects_101_function_selections(self):
        from pydantic import ValidationError
        from subscriptions.app import SignupRequest

        request = SignupRequest(
            contactName="Test Buyer",
            email="buyer@example.test",
            company="Test Company",
            tier="enterprise",
            functions=[f"function-{index:03d}" for index in range(100)],
        )
        self.assertEqual(len(request.functions), 100)
        with self.assertRaises(ValidationError):
            SignupRequest(
                contactName="Test Buyer",
                email="buyer@example.test",
                company="Test Company",
                tier="enterprise",
                functions=[f"function-{index:03d}" for index in range(101)],
            )

    def test_altered_payload_unknown_key_and_wrong_signature_are_rejected(self):
        token = _sign(self.signing_key, self.claims())
        protected, payload, signature = token.split(".")
        altered_claims = self.claims(function_ids=["alpha", "beta", "gamma", "delta", "epsilon", "zeta"])
        altered_payload = _b64url(json.dumps(altered_claims, separators=(",", ":"), sort_keys=True).encode())
        with self.assertRaisesRegex(LicenseValidationError, "signature") as altered:
            self.service.install_entitlement(f"{protected}.{altered_payload}.{signature}")
        self.assertEqual(altered.exception.code, "invalid_signature")

        with self.assertRaises(LicenseValidationError) as unknown:
            self.service.install_entitlement(_sign(self.signing_key, self.claims(), kid="unknown-key"))
        self.assertEqual(unknown.exception.code, "unknown_signing_key")

        other_key = Ed25519PrivateKey.generate()
        with self.assertRaises(LicenseValidationError) as wrong:
            self.service.install_entitlement(_sign(other_key, self.claims()))
        self.assertEqual(wrong.exception.code, "invalid_signature")

    def test_entitlement_is_bound_to_local_key_device_and_site(self):
        with self.assertRaises(LicenseValidationError) as wrong_key:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(device_public_key_sha256="f" * 64))
            )
        self.assertEqual(wrong_key.exception.code, "wrong_device_key")

        self.install()
        with self.assertRaises(LicenseValidationError) as wrong_device:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(device_id="device-two", revision=2))
            )
        self.assertEqual(wrong_device.exception.code, "wrong_device")
        with self.assertRaises(LicenseValidationError) as wrong_site:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(site_id="site-two", revision=2))
            )
        self.assertEqual(wrong_site.exception.code, "wrong_site")

    def test_catalog_mismatch_and_starter_tier_escalation_are_rejected(self):
        with self.assertRaises(LicenseValidationError) as mismatch:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(catalog_sha256="0" * 64))
            )
        self.assertEqual(mismatch.exception.code, "catalog_mismatch")

        with self.assertRaises(LicenseValidationError) as tier:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(function_ids=["pro-only"]))
            )
        self.assertEqual(tier.exception.code, "plan_tier_violation")

    def test_revision_rollback_and_same_revision_replacement_are_rejected(self):
        self.install(self.claims(revision=2, license_id="lic-revision-two"))
        cached = (self.root / "licensing" / "entitlement.jws").read_text(encoding="utf-8")

        with self.assertRaises(LicenseValidationError) as rollback:
            self.service.install_entitlement(_sign(self.signing_key, self.claims(revision=1)))
        self.assertEqual(rollback.exception.code, "revision_rollback")
        self.assertEqual((self.root / "licensing" / "entitlement.jws").read_text(encoding="utf-8"), cached)

        with self.assertRaises(LicenseValidationError) as conflict:
            self.service.install_entitlement(
                _sign(self.signing_key, self.claims(revision=2, license_id="different-license"))
            )
        self.assertEqual(conflict.exception.code, "revision_conflict")
        self.assertEqual((self.root / "licensing" / "entitlement.jws").read_text(encoding="utf-8"), cached)

    def test_authoritative_inactive_revision_supersedes_active_entitlement(self):
        self.install(self.claims(revision=1, license_id="lic-active"))
        requested = self.config({"camera-one": ["alpha"]})
        self.assertTrue(self.service.authorize_configuration(requested).authorized)

        revoked_token = _sign(
            self.signing_key,
            self.claims(
                revision=2,
                license_id="lic-revoked",
                status="revoked",
                function_ids=[],
                capabilities=[],
            ),
        )
        installed = self.service.install_entitlement(revoked_token)

        self.assertEqual(installed["state"], "invalid")
        self.assertEqual(installed["reason"], "subscription_inactive")
        self.assertFalse(installed["paid_runtime_authorized"])
        self.assertEqual(
            (self.root / "licensing" / "entitlement.jws").read_text(encoding="ascii").strip(),
            revoked_token,
        )
        denied = self.service.authorize_configuration(requested)
        self.assertFalse(denied.authorized)
        self.assertEqual(denied.reason, "subscription_inactive")
        self.assertFalse(self.service.allows_capability("access-control"))

    def test_bound_device_cannot_reset_revision_by_deleting_entitlement_and_state(self):
        self.install(self.claims(revision=2, license_id="lic-revision-two"))
        (self.root / "licensing" / "entitlement.jws").unlink()
        (self.root / "licensing" / "state.json").unlink()

        with self.assertRaises(LicenseValidationError) as reset:
            self.service.install_entitlement(_sign(self.signing_key, self.claims(revision=1)))

        self.assertEqual(reset.exception.code, "license_state_invalid")

    def test_cached_entitlement_must_match_durable_digest_and_revision(self):
        self.install(self.claims(revision=1, license_id="lic-original"))
        conflicting = _sign(
            self.signing_key,
            self.claims(revision=1, license_id="lic-conflicting"),
        )
        (self.root / "licensing" / "entitlement.jws").write_text(
            conflicting + "\n", encoding="ascii"
        )

        denied = self.service.authorize_configuration(self.config({"camera-one": ["alpha"]}))

        self.assertFalse(denied.authorized)
        self.assertEqual(denied.reason, "license_state_mismatch")

    def test_concurrent_installs_cannot_let_lower_revision_win(self):
        self.install(self.claims(revision=1, license_id="lic-revision-one"))
        lower_read = threading.Event()

        class SlowLowerRevisionService(LicenseService):
            delayed = False

            def _state(inner_self):
                state = super()._state()
                if threading.current_thread().name == "lower-revision":
                    lower_read.set()
                return state

            def _write_state(inner_self, state):
                if threading.current_thread().name == "lower-revision" and not inner_self.delayed:
                    inner_self.delayed = True
                    time.sleep(0.15)
                return super()._write_state(state)

        common = {
            "directory": self.root / "licensing",
            "trusted_keys": {"test-2026": self.signing_key.public_key()},
            "catalog_sha256": self.catalog_hash,
            "installed_function_tiers": {row["id"]: row["tier"] for row in self.catalog},
            "clock": lambda: self.now,
        }
        lower_service = SlowLowerRevisionService(**common)
        higher_service = LicenseService(**common)
        lower_token = _sign(
            self.signing_key,
            self.claims(revision=2, license_id="lic-revision-two"),
        )
        higher_token = _sign(
            self.signing_key,
            self.claims(revision=3, license_id="lic-revision-three"),
        )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="license-test") as executor:
            lower = executor.submit(
                lambda: (
                    setattr(threading.current_thread(), "name", "lower-revision"),
                    lower_service.install_entitlement(lower_token),
                )[1]
            )
            self.assertTrue(lower_read.wait(2))
            higher = executor.submit(higher_service.install_entitlement, higher_token)
            lower.result(timeout=3)
            higher.result(timeout=3)

        final_status = LicenseService(**common).status()
        self.assertEqual(final_status["state"], "current")
        self.assertEqual(final_status["revision"], 3)
        self.assertEqual(
            (self.root / "licensing" / "entitlement.jws").read_text(encoding="ascii").strip(),
            higher_token,
        )

    def test_authorization_state_write_cannot_overwrite_newer_entitlement(self):
        self.install(self.claims(revision=1, license_id="lic-revision-one"))
        authorization_writing = threading.Event()

        class SlowAuthorizationService(LicenseService):
            delayed = False

            def _write_state(inner_self, state):
                if threading.current_thread().name == "authorizer" and not inner_self.delayed:
                    inner_self.delayed = True
                    authorization_writing.set()
                    time.sleep(0.15)
                return super()._write_state(state)

        common = {
            "directory": self.root / "licensing",
            "trusted_keys": {"test-2026": self.signing_key.public_key()},
            "catalog_sha256": self.catalog_hash,
            "installed_function_tiers": {row["id"]: row["tier"] for row in self.catalog},
            "clock": lambda: self.now,
        }
        slow = SlowAuthorizationService(**common)
        installer = LicenseService(**common)
        higher_token = _sign(
            self.signing_key,
            self.claims(revision=2, license_id="lic-revision-two"),
        )
        requested = self.config({"camera-one": ["alpha"]})
        with ThreadPoolExecutor(max_workers=2) as executor:
            authorizer = executor.submit(
                lambda: (
                    setattr(threading.current_thread(), "name", "authorizer"),
                    slow.authorize_configuration(requested),
                )[1]
            )
            self.assertTrue(authorization_writing.wait(2))
            installed = executor.submit(installer.install_entitlement, higher_token)
            self.assertTrue(authorizer.result(timeout=3).authorized)
            installed.result(timeout=3)

        final_status = LicenseService(**common).status()
        self.assertEqual(final_status["state"], "current")
        self.assertEqual(final_status["revision"], 2)

    def test_catalog_hash_is_order_independent_and_rejects_duplicate_ids(self):
        self.assertEqual(self.catalog_hash, catalog_sha256(list(reversed(self.catalog))))
        with self.assertRaises(LicenseValidationError) as duplicate:
            catalog_sha256([self.catalog[0], dict(self.catalog[0])])
        self.assertEqual(duplicate.exception.code, "catalog_invalid")

    def test_compact_jws_rejects_duplicate_claims_and_noncanonical_base64url(self):
        header = {"alg": "EdDSA", "kid": "test-2026", "typ": "NEXUS-ENTITLEMENT"}
        protected = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
        claims_json = json.dumps(self.claims(), separators=(",", ":"), sort_keys=True)
        duplicate_json = claims_json[:-1] + ',"revision":2}'
        duplicate_token = _sign_segments(
            self.signing_key,
            protected,
            _b64url(duplicate_json.encode("utf-8")),
        )
        with self.assertRaises(LicenseValidationError) as duplicate:
            self.service.install_entitlement(duplicate_token)
        self.assertEqual(duplicate.exception.code, "invalid_claims")

        payload = _b64url((claims_json + " ").encode("utf-8"))
        noncanonical_payload = _noncanonical_b64url(payload)
        noncanonical_token = _sign_segments(
            self.signing_key,
            protected,
            noncanonical_payload,
        )
        with self.assertRaises(LicenseValidationError) as noncanonical:
            self.service.install_entitlement(noncanonical_token)
        self.assertEqual(noncanonical.exception.code, "malformed_entitlement")

    def test_starter_signed_limits_cannot_exceed_plan_ceiling(self):
        with self.assertRaises(LicenseValidationError) as ceiling:
            self.service.install_entitlement(
                _sign(
                    self.signing_key,
                    self.claims(
                        limits={"sites": 1, "streams": 9, "distinct_functions": 5}
                    ),
                )
            )
        self.assertEqual(ceiling.exception.code, "plan_limit_violation")

    def test_professional_plan_rejects_enterprise_grants_and_excess_limits(self):
        with self.assertRaises(LicenseValidationError) as tier:
            self.service.install_entitlement(
                _sign(
                    self.signing_key,
                    self.claims(
                        plan="professional",
                        function_ids=["enterprise-only"],
                        limits={"sites": 1, "streams": 24, "distinct_functions": 12},
                    ),
                )
            )
        self.assertEqual(tier.exception.code, "plan_tier_violation")

        with self.assertRaises(LicenseValidationError) as ceiling:
            self.service.install_entitlement(
                _sign(
                    self.signing_key,
                    self.claims(
                        plan="professional",
                        function_ids=["pro-only"],
                        limits={"sites": 1, "streams": 25, "distinct_functions": 12},
                    ),
                )
            )
        self.assertEqual(ceiling.exception.code, "plan_limit_violation")

    def test_unknown_capabilities_and_non_zulu_timestamps_are_rejected(self):
        with self.assertRaises(LicenseValidationError) as capability:
            self.service.install_entitlement(
                _sign(
                    self.signing_key,
                    self.claims(capabilities=["future-unknown-control"]),
                )
            )
        self.assertEqual(capability.exception.code, "unknown_capability")

        with self.assertRaises(LicenseValidationError) as timestamp:
            self.service.install_entitlement(
                _sign(
                    self.signing_key,
                    self.claims(
                        issued_at=datetime.fromtimestamp(
                            self.now - 60, timezone.utc
                        ).isoformat(),
                    ),
                )
            )
        self.assertEqual(timestamp.exception.code, "invalid_claims")

    def test_grace_freezes_full_analytics_configuration(self):
        original = self.config({"camera-one": ["alpha"]})
        original["detector_settings"] = {"alpha": {"threshold": 0.6}}
        self.install(
            self.claims(
                expires_at=_timestamp(self.now + 10),
                grace_until=_timestamp(self.now + 20),
            )
        )
        self.assertTrue(self.service.authorize_configuration(original).authorized)
        self.now += 11

        changed = copy.deepcopy(original)
        changed["detector_settings"]["alpha"]["threshold"] = 0.1
        denied = self.service.authorize_configuration(changed)

        self.assertFalse(denied.authorized)
        self.assertEqual(denied.reason, "grace_configuration_changed")

    def test_grace_allows_only_last_authorized_mapping_then_beyond_grace_disables_analytics(self):
        original = self.config({"camera-one": ["alpha"], "camera-two": ["alpha"]})
        frozen = copy.deepcopy(original)
        self.install(
            self.claims(
                expires_at=_timestamp(self.now + 10),
                grace_until=_timestamp(self.now + 20),
            )
        )
        self.assertTrue(self.service.authorize_configuration(original).authorized)

        self.now += 11
        grace = self.service.authorize_configuration(original)
        self.assertTrue(grace.authorized)
        self.assertEqual(grace.state, "grace")

        changed = self.config({"camera-one": ["alpha", "beta"], "camera-two": ["alpha"]})
        blocked_change = self.service.authorize_configuration(changed)
        self.assertFalse(blocked_change.authorized)
        self.assertEqual(blocked_change.reason, "grace_configuration_changed")
        self.assertTrue(all(not camera["detectors"] for camera in blocked_change.effective_config["cameras"]))

        self.now += 10
        expired = self.service.authorize_configuration(original)
        self.assertFalse(expired.authorized)
        self.assertEqual(expired.state, "invalid")
        self.assertEqual(expired.reason, "expired")
        self.assertTrue(all(not camera["detectors"] for camera in expired.effective_config["cameras"]))
        self.assertEqual(original, frozen)
        self.assertTrue((self.root / "licensing" / "entitlement.jws").is_file())

    def test_function_stream_and_distinct_limits_fail_closed(self):
        self.install(self.claims(function_ids=["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]))

        sixth = self.service.authorize_configuration(
            self.config({"camera-one": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]})
        )
        self.assertFalse(sixth.authorized)
        self.assertEqual(sixth.reason, "distinct_function_limit")

        ninth_stream = self.service.authorize_configuration(
            self.config({f"camera-{index}": ["alpha"] for index in range(9)})
        )
        self.assertFalse(ninth_stream.authorized)
        self.assertEqual(ninth_stream.reason, "stream_limit")

        repeated = self.service.authorize_configuration(
            self.config({f"camera-{index}": ["alpha"] for index in range(8)})
        )
        self.assertTrue(repeated.authorized)
        self.assertEqual(repeated.distinct_function_count, 1)
        self.assertEqual(repeated.stream_count, 8)

    def test_ungranted_and_uninstalled_functions_never_reach_effective_configuration(self):
        self.install()
        ungranted = self.service.authorize_configuration(self.config({"camera-one": ["zeta"]}))
        self.assertFalse(ungranted.authorized)
        self.assertEqual(ungranted.reason, "function_not_granted")
        self.assertEqual(ungranted.effective_config["cameras"][0]["detectors"], [])

        service = LicenseService(
            directory=self.root / "other-licensing",
            trusted_keys={"test-2026": self.signing_key.public_key()},
            catalog_sha256=self.catalog_hash,
            installed_function_tiers={"alpha": "starter"},
            clock=lambda: self.now,
        )
        registration = service.device_registration()
        claims = self.claims(
            device_public_key_sha256=registration["public_key_sha256"],
            function_ids=["alpha", "beta"],
        )
        service.install_entitlement(_sign(self.signing_key, claims))
        unavailable = service.authorize_configuration(self.config({"camera-one": ["beta"]}))
        self.assertFalse(unavailable.authorized)
        self.assertEqual(unavailable.reason, "update_required")
        self.assertEqual(unavailable.effective_config["cameras"][0]["detectors"], [])

    def test_unlicensed_system_keeps_setup_and_diagnostics_configuration_but_runs_no_paid_functions(self):
        requested = self.config({"camera-one": ["alpha"]})
        frozen = copy.deepcopy(requested)

        denied = self.service.authorize_configuration(requested)

        self.assertFalse(denied.authorized)
        self.assertEqual(denied.state, "unlicensed")
        self.assertEqual(denied.reason, "entitlement_missing")
        self.assertEqual(denied.effective_config["cameras"][0]["detectors"], [])
        self.assertEqual(requested, frozen)
        empty = self.service.validate_configuration(self.config({"camera-one": []}))
        self.assertTrue(empty.authorized)

    def test_clock_rollback_invalidates_paid_authorization_without_removing_entitlement(self):
        self.install()
        requested = self.config({"camera-one": ["alpha"]})
        self.assertTrue(self.service.authorize_configuration(requested).authorized)

        self.now -= 601
        rollback = self.service.authorize_configuration(requested)

        self.assertFalse(rollback.authorized)
        self.assertEqual(rollback.reason, "clock_rollback")
        self.assertTrue((self.root / "licensing" / "entitlement.jws").is_file())

    def test_explicit_signed_capability_controls_door_actions_and_expires_with_lease(self):
        self.install(
            self.claims(
                capabilities=["access-control"],
                expires_at=_timestamp(self.now + 10),
                grace_until=_timestamp(self.now + 20),
            )
        )
        self.assertTrue(self.service.allows_capability("access-control"))
        self.assertFalse(self.service.allows_capability("unsupported-control"))

        self.now += 21
        self.assertFalse(self.service.allows_capability("access-control"))

    def test_identity_and_license_state_files_are_owner_only(self):
        self.install()
        self.service.authorize_configuration(self.config({"camera-one": ["alpha"]}))
        for name in ("device-private-key.pem", "device.json", "entitlement.jws", "state.json"):
            path = self.root / "licensing" / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, name)

    def test_pipeline_filters_before_detector_construction_and_rechecks_beyond_grace(self):
        from main import Pipeline

        class Probe:
            name = "alpha"

            def __init__(self, settings):
                self.settings = settings

            def process(self, *_args):
                return None

        requested = self.config({"camera-one": ["alpha"]})
        frozen = copy.deepcopy(requested)
        with patch.dict(
            os.environ,
            {"VISION_DATA": str(self.root / "data"), "BASE44_ALERT_URL": "", "EXTRA_WEBHOOK_URL": ""},
            clear=False,
        ):
            unlicensed = Pipeline(requested, {"alpha": Probe}, license_service=self.service)
            self.assertEqual(unlicensed.camera_detectors["camera-one"], [])
            self.assertEqual(requested, frozen)

            self.install(
                self.claims(
                    expires_at=_timestamp(self.now + 10),
                    grace_until=_timestamp(self.now + 20),
                )
            )
            licensed = Pipeline(requested, {"alpha": Probe}, license_service=self.service)
            self.assertEqual([detector.name for detector in licensed.camera_detectors["camera-one"]], ["alpha"])
            self.now += 21
            changed = licensed.refresh_license()
            self.assertTrue(changed)
            self.assertEqual(licensed.camera_detectors["camera-one"], [])
            self.assertEqual(licensed.license_authorization.reason, "expired")
            self.assertEqual(requested, frozen)

    def test_setup_accepts_diagnostics_only_but_rejects_unentitled_detector_mapping(self):
        from setup_service import SetupService, SetupStore, SetupValidationError
        from unittest.mock import Mock

        factory = Mock()
        factory.return_value.cameras.return_value = [
            {
                "id": "camera-one",
                "name": "North Entry",
                "model": "Camera",
                "state": "CONNECTED",
                "rtsp": "rtsps://nvr.invalid:7441/low",
                "rtsp_enabled": True,
                "stream": {"width": 1280, "height": 720, "fps": 15},
            }
        ]
        setup = SetupService(
            SetupStore(self.root / "sites.yaml", self.root / "runtime-settings.json", self.root / "certs"),
            protect_client_factory=factory,
            allowed_detectors={"alpha"},
            configuration_validator=self.service.validate_configuration,
        )
        connection = {
            "host": "nvr.invalid",
            "port": 443,
            "username": "local-service",
            "password": "not-returned",
            "tls_mode": "system",
        }
        with self.assertRaisesRegex(SetupValidationError, "signed entitlement"):
            setup.configure(
                site_name="Site",
                timezone_name="UTC",
                connection=connection,
                selected_camera_ids=["camera-one"],
                detectors_by_camera={"camera-one": ["alpha"]},
            )

        with self.assertRaisesRegex(SetupValidationError, "unknown camera"):
            setup.configure(
                site_name="Site",
                timezone_name="UTC",
                connection=connection,
                selected_camera_ids=["camera-one"],
                detectors_by_camera={"camera-one": [], "camera-unknown": []},
            )

        result = setup.configure(
            site_name="Site",
            timezone_name="UTC",
            connection=connection,
            selected_camera_ids=["camera-one"],
            detectors_by_camera={"camera-one": []},
        )
        self.assertTrue(result["saved"])

        self.service.installed_function_tiers["video_search"] = None
        setup.allowed_detectors.add("video_search")
        self.install(self.claims(function_ids=["video_search"]))
        core_result = setup.configure(
            site_name="Site",
            timezone_name="UTC",
            connection=connection,
            selected_camera_ids=["camera-one"],
            detectors_by_camera={"camera-one": ["video_search"]},
        )
        self.assertTrue(core_result["saved"])
        persisted = (self.root / "sites.yaml").read_text(encoding="utf-8")
        self.assertIn("video_search", persisted)

    def test_setup_request_models_forbid_unknown_fields(self):
        from pydantic import ValidationError
        from setup_api import SaveSetupRequest

        payload = {
            "site_name": "Site",
            "timezone": "UTC",
            "connection": {
                "host": "nvr.invalid",
                "port": 443,
                "username": "local-service",
                "password": "redacted-fixture",
                "tls_mode": "system",
            },
            "selected_camera_ids": ["camera-one"],
            "detectors_by_camera": {"camera-one": []},
            "unexpected_authorization": True,
        }
        with self.assertRaises(ValidationError):
            SaveSetupRequest.model_validate(payload)

    def test_admin_licensing_routes_install_entitlement_without_exposing_secrets(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from fastapi.testclient import TestClient
        import api

        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            license_service=self.service,
            licensing_enforced=True,
            requested_detector_count=0,
            license_authorization=SimpleNamespace(state="unlicensed", reason="entitlement_missing"),
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        token = _sign(self.signing_key, self.claims())
        with patch.dict(os.environ, {"VISION_ADMIN_TOKEN": "unit-test-admin-token"}, clear=False), patch(
            "subscriptions.store.init_db", return_value=None
        ):
            client = TestClient(api.create_app(pipeline, streams, setup_service=setup))
            self.assertEqual(client.get("/api/licensing/status").status_code, 401)
            headers = {"x-admin-token": "unit-test-admin-token"}
            device = client.get("/api/licensing/device", headers=headers)
            self.assertEqual(device.status_code, 200)
            self.assertEqual(device.json()["algorithm"], "Ed25519")
            self.assertNotIn("private", json.dumps(device.json()).lower())

            installed = client.post(
                "/api/licensing/entitlement", headers=headers, json={"entitlement": token}
            )
            self.assertEqual(installed.status_code, 200, installed.text)
            self.assertEqual(installed.json()["state"], "current")
            self.assertNotIn(token, installed.text)

            protected, payload, signature = token.split(".")
            signature_bytes = bytearray(
                base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            )
            signature_bytes[0] ^= 1
            bad = f"{protected}.{payload}.{_b64url(bytes(signature_bytes))}"
            rejected = client.post(
                "/api/licensing/entitlement", headers=headers, json={"entitlement": bad}
            )
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(rejected.json()["detail"]["code"], "invalid_signature")
            self.assertNotIn(bad, rejected.text)

    def test_door_control_requires_both_control_token_and_signed_capability(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from fastapi.testclient import TestClient
        import api

        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        access = Mock(enabled=True)
        access.unlock.return_value = True
        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            license_service=self.service,
            licensing_enforced=True,
            requested_detector_count=0,
            license_authorization=SimpleNamespace(state="unlicensed", reason="entitlement_missing"),
            access=access,
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        with patch.dict(
            os.environ,
            {
                "VISION_ADMIN_TOKEN": "unit-test-admin-token",
                "VISION_CONTROL_TOKEN": "unit-test-control-token",
            },
            clear=False,
        ), patch("subscriptions.store.init_db", return_value=None):
            client = TestClient(api.create_app(pipeline, streams, setup_service=setup))
            headers = {"Authorization": "Bearer unit-test-control-token"}
            denied = client.post("/unlock/door-one", headers=headers)
            self.assertEqual(denied.status_code, 410)
            access.unlock.assert_not_called()

            self.install(self.claims(capabilities=["access-control"]))
            allowed = client.post("/unlock/door-one", headers=headers)
            self.assertEqual(allowed.status_code, 410, allowed.text)
            access.unlock.assert_not_called()

    def test_access_adapter_fails_closed_without_signed_control_capability(self):
        import unifi_access

        with patch.dict(
            os.environ,
            {"UNIFI_ACCESS_HOST": "access.invalid", "UNIFI_ACCESS_TOKEN": "local-token"},
            clear=False,
        ):
            denied = unifi_access.AccessPoller(
                lambda _event: None,
                capability_authorizer=lambda capability: False,
            )
            allowed = unifi_access.AccessPoller(
                lambda _event: None,
                capability_authorizer=lambda capability: capability == "access-control",
            )
        response = SimpleNamespace(status_code=200)
        with patch("unifi_access.requests.put", return_value=response) as request:
            self.assertFalse(denied.unlock("door-one"))
            request.assert_not_called()
            self.assertTrue(allowed.unlock("door-one"))
            request.assert_called_once()

    def test_public_health_redacts_license_and_appliance_identifiers(self):
        from fastapi.testclient import TestClient
        import api

        self.install()
        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            license_service=self.service,
            licensing_enforced=True,
            requested_detector_count=0,
            license_authorization=SimpleNamespace(state="current", reason="authorized"),
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        with patch("subscriptions.store.init_db", return_value=None):
            health = TestClient(api.create_app(pipeline, streams, setup_service=setup)).get("/health")

        self.assertEqual(health.status_code, 200)
        licensing = health.json()["licensing"]
        self.assertEqual(
            set(licensing),
            {"state", "reason", "paid_runtime_authorized"},
        )
        serialized = json.dumps(health.json())
        for sensitive in ("lic-current", "org-one", "site-one", "device-one"):
            self.assertNotIn(sensitive, serialized)

    def test_public_health_uses_runtime_license_snapshot_without_service_io(self):
        from fastapi.testclient import TestClient
        import api

        self.install()
        authorization = self.service.authorize_configuration(
            self.config({"camera-one": ["alpha"]})
        )
        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            license_service=self.service,
            licensing_enforced=True,
            requested_detector_count=1,
            license_authorization=authorization,
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        with patch("subscriptions.store.init_db", return_value=None), patch.object(
            self.service, "status", wraps=self.service.status
        ) as status:
            health = TestClient(
                api.create_app(pipeline, streams, setup_service=setup)
            ).get("/health")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["licensing"]["state"], "current")
        self.assertTrue(health.json()["licensing"]["paid_runtime_authorized"])
        status.assert_not_called()

    def test_enforcement_catalog_hash_includes_all_core_detector_contracts(self):
        from activation.runtime import CORE_FUNCTIONS, build_license_service

        expected_core_ids = {
            "fall",
            "bed_exit",
            "weapon",
            "ppe",
            "near_miss",
            "elopement",
            "alpr",
            "video_search",
            "tailgating",
            "smoke_flame",
        }
        self.assertEqual({row["id"] for row in CORE_FUNCTIONS}, expected_core_ids)
        catalog_path = self.root / "catalog-with-core.json"
        catalog_path.write_text(json.dumps(list(reversed(self.catalog))), encoding="utf-8")
        raw_public_key = self.signing_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        trust_path = self.root / "trusted-core-keys.json"
        trust_path.write_text(
            json.dumps(
                {
                    "schema": "nexus.entitlement-keys/v1",
                    "keys": {"test-2026": _b64url(raw_public_key)},
                }
            ),
            encoding="utf-8",
        )

        service = build_license_service(
            installed_function_ids=expected_core_ids | {"alpha"},
            directory=self.root / "core-runtime-license",
            trust_store_path=trust_path,
            catalog_path=catalog_path,
            clock=lambda: self.now,
        )

        expected_hash = catalog_sha256([*self.catalog, *CORE_FUNCTIONS])
        self.assertEqual(service.catalog_sha256, expected_hash)
        self.assertEqual(service.installed_function_tiers["video_search"], "pro")
        self.assertEqual(service.installed_function_tiers["weapon"], "enterprise")

    def test_runtime_factory_uses_canonical_catalog_and_baked_public_key_set(self):
        from activation.runtime import build_license_service

        catalog_path = self.root / "catalog.json"
        catalog_path.write_text(json.dumps(self.catalog, indent=2) + "\n", encoding="utf-8")
        raw_public_key = self.signing_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        trust_path = self.root / "trusted-entitlement-keys.json"
        trust_path.write_text(
            json.dumps(
                {
                    "schema": "nexus.entitlement-keys/v1",
                    "keys": {"test-2026": _b64url(raw_public_key)},
                }
            ),
            encoding="utf-8",
        )
        service = build_license_service(
            installed_function_ids={"alpha", "pro-only"},
            directory=self.root / "runtime-license",
            trust_store_path=trust_path,
            catalog_path=catalog_path,
            clock=lambda: self.now,
        )
        registration = service.device_registration()
        service.install_entitlement(
            _sign(
                self.signing_key,
                self.claims(
                    device_public_key_sha256=registration["public_key_sha256"],
                    function_ids=["alpha"],
                    catalog_sha256=service.catalog_sha256,
                ),
            )
        )
        self.assertTrue(
            service.authorize_configuration(self.config({"camera-one": ["alpha"]})).authorized
        )

    def test_release_inputs_pin_ed25519_runtime_and_public_only_trust_store(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("cryptography==50.0.0", requirements)
        self.assertIn("cryptography==50.0.0", lock)
        self.assertIn("cffi==2.0.0", lock)
        self.assertIn("pycparser==3.0", lock)
        trust = json.loads(
            (ROOT / "config" / "trusted-entitlement-keys.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(trust), {"schema", "keys"})
        self.assertEqual(trust["schema"], "nexus.entitlement-keys/v1")
        self.assertIsInstance(trust["keys"], dict)
        self.assertNotIn("private", json.dumps(trust).lower())

    def test_startup_degrades_to_management_plane_when_config_or_licensing_fails(self):
        import main

        class Probe:
            name = "alpha"

            def __init__(self, _settings):
                pass

            def process(self, *_args):
                return None

        requested = self.config({"camera-one": ["alpha"]})
        valid_path = self.root / "valid-sites.yaml"
        valid_path.write_text(json.dumps(requested), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "VISION_LICENSE_DIR": str(self.root / "degraded-license"),
                "VISION_DATA": str(self.root / "degraded-data"),
                "BASE44_ALERT_URL": "",
                "EXTRA_WEBHOOK_URL": "",
            },
            clear=False,
        ), patch("main.load_detectors", return_value={"alpha": Probe}), patch(
            "main.build_license_service",
            side_effect=LicenseValidationError("trust_store_invalid", "unavailable"),
        ):
            degraded = main.assemble_pipeline(valid_path)

        self.assertTrue(degraded.licensing_enforced)
        self.assertEqual(degraded.camera_detectors["camera-one"], [])
        self.assertEqual(degraded.license_authorization.reason, "entitlement_missing")

        malformed_path = self.root / "malformed-sites.yaml"
        malformed_path.write_text("site: [unterminated", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "VISION_LICENSE_DIR": str(self.root / "malformed-license"),
                "VISION_DATA": str(self.root / "malformed-data"),
            },
            clear=False,
        ), patch("main.load_detectors", side_effect=RuntimeError("broken registry")):
            empty = main.assemble_pipeline(malformed_path)
        self.assertTrue(empty.licensing_enforced)
        self.assertEqual(empty.cameras, [])
        self.assertEqual(empty.camera_detectors, {})

    def test_paid_video_search_requires_explicit_signed_function_grant(self):
        from fastapi.testclient import TestClient
        import api

        setup = Mock()
        setup.status.return_value = {"configured": False, "camera_count": 0}
        pipeline = SimpleNamespace(
            site="Site",
            cameras=[],
            alerts=SimpleNamespace(stats=lambda: {}),
            camera_detectors={},
            detector_failures={},
            license_service=self.service,
            licensing_enforced=True,
            requested_detector_count=0,
            license_authorization=SimpleNamespace(state="unlicensed", reason="entitlement_missing"),
        )
        streams = SimpleNamespace(workers=[], status=lambda: [])
        headers = {"x-admin-token": "unit-test-admin-token"}
        with patch.dict(
            os.environ,
            {"VISION_ADMIN_TOKEN": "unit-test-admin-token"},
            clear=False,
        ), patch("subscriptions.store.init_db", return_value=None), patch(
            "detectors.video_search.search", return_value=[]
        ) as search:
            client = TestClient(api.create_app(pipeline, streams, setup_service=setup))
            denied = client.get("/search?q=truck", headers=headers)
            self.assertEqual(denied.status_code, 403)
            search.assert_not_called()

            self.service.installed_function_tiers["video_search"] = None
            self.install(self.claims(function_ids=["video_search"]))
            allowed = client.get("/search?q=truck", headers=headers)
            self.assertEqual(allowed.status_code, 200, allowed.text)
            search.assert_called_once_with("truck", limit=10)

    def test_production_entrypoint_enforces_license_at_startup_and_during_runtime(self):
        source = (SRC / "main.py").read_text(encoding="utf-8")
        self.assertIn("from activation.runtime import build_license_service", source)
        self.assertRegex(source, r"license_service = build_license_service\(detector_classes\)")
        self.assertIn(
            "Pipeline(config, detector_classes, license_service=license_service)",
            source,
        )
        self.assertIn("pipeline.refresh_license()", source)


if __name__ == "__main__":
    unittest.main()
