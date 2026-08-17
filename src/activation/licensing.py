"""Cryptographic subscription licensing for the local Nexus Vision appliance.

The public interface is deliberately small: install one signed entitlement, inspect a
redacted status, authorize a requested configuration, and check signed capabilities.
Signup records, browser state, and local YAML never become subscription authority.
"""
from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_SCHEMA = "nexus.entitlement/v1"
_HEADER_TYPE = "NEXUS-ENTITLEMENT"
_BINDING_SCHEMA = "nexus.device-binding/v1"
_STATE_SCHEMA = "nexus.license-state/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FUNCTION_ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_JWS_BYTES = 64 * 1024
_MAX_FUNCTION_GRANTS = 512
_CLOCK_ROLLBACK_TOLERANCE_SECONDS = 300
_CURRENT_STATUSES = {"active", "trialing"}
_GRACE_STATUSES = _CURRENT_STATUSES | {"past_due"}
_INACTIVE_STATUSES = {"canceled", "cancelled", "revoked", "suspended", "unpaid", "inactive"}
_KNOWN_CAPABILITIES = frozenset({"access-control"})
_REQUIRED_CLAIMS = {
    "schema",
    "license_id",
    "organization_id",
    "site_id",
    "device_id",
    "device_public_key_sha256",
    "plan",
    "status",
    "limits",
    "function_ids",
    "capabilities",
    "catalog_sha256",
    "revision",
    "issued_at",
    "not_before",
    "expires_at",
    "grace_until",
}


class LicenseValidationError(ValueError):
    """A non-secret licensing error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Entitlement:
    license_id: str
    organization_id: str
    site_id: str
    device_id: str
    device_public_key_sha256: str
    plan: str
    subscription_status: str
    site_limit: int
    stream_limit: int
    distinct_function_limit: int
    function_ids: frozenset[str]
    capabilities: frozenset[str]
    catalog_sha256: str
    revision: int
    issued_at: int
    not_before: int
    expires_at: int
    grace_until: int


@dataclass(frozen=True)
class VerifiedEntitlement:
    entitlement: Entitlement
    state: str
    reason: str


@dataclass(frozen=True)
class RuntimeAuthorization:
    authorized: bool
    state: str
    reason: str
    effective_config: dict[str, Any]
    stream_count: int
    distinct_function_count: int
    granted_function_ids: frozenset[str]


def catalog_sha256(catalog: Any) -> str:
    """Hash a validated catalog projection independent of row/file ordering."""
    if not isinstance(catalog, list) or len(catalog) > 512:
        raise LicenseValidationError("catalog_invalid", "entitlement catalog is invalid")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in catalog:
        if not isinstance(row, dict):
            raise LicenseValidationError("catalog_invalid", "entitlement catalog is invalid")
        function_id = row.get("id")
        if (
            not isinstance(function_id, str)
            or not _FUNCTION_ID.fullmatch(function_id)
            or function_id in seen
        ):
            raise LicenseValidationError("catalog_invalid", "entitlement catalog IDs are invalid")
        seen.add(function_id)
        rows.append(copy.deepcopy(row))
    rows.sort(key=lambda row: row["id"])
    try:
        canonical = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LicenseValidationError("catalog_invalid", "entitlement catalog is invalid") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _b64url_decode(segment: str, *, maximum: int, code: str) -> bytes:
    if not segment or len(segment) > maximum or "=" in segment or not _B64URL.fullmatch(segment):
        raise LicenseValidationError(code, "entitlement encoding is invalid")
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, TypeError) as exc:
        raise LicenseValidationError(code, "entitlement encoding is invalid") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != segment:
        raise LicenseValidationError(code, "entitlement encoding is not canonical")
    return decoded


def _json_object(raw: bytes, *, code: str) -> dict[str, Any]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise LicenseValidationError(code, "entitlement JSON is invalid") from exc
    if not isinstance(value, dict):
        raise LicenseValidationError(code, "entitlement JSON must be an object")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid")
    return value


def _strict_positive_int(value: Any, field: str, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid")
    return value


def _timestamp(value: Any, field: str) -> int:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid") from exc
    timestamp = int(parsed.timestamp())
    if not 946684800 <= timestamp <= 4102444800:
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is outside the supported range")
    return timestamp


def _string_set(value: Any, field: str, pattern: re.Pattern[str], maximum: int) -> frozenset[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or len(item) > 80 or not pattern.fullmatch(item) or item in result:
            raise LicenseValidationError("invalid_claims", f"entitlement {field} is invalid")
        result.add(item)
    return frozenset(result)


def _parse_claims(payload: dict[str, Any]) -> Entitlement:
    if set(payload) != _REQUIRED_CLAIMS or payload.get("schema") != _SCHEMA:
        raise LicenseValidationError("invalid_claims", "entitlement schema or claim set is invalid")
    limits = payload.get("limits")
    if not isinstance(limits, dict) or set(limits) != {"sites", "streams", "distinct_functions"}:
        raise LicenseValidationError("invalid_claims", "entitlement limits are invalid")
    plan = payload.get("plan")
    if plan not in {"starter", "professional", "enterprise"}:
        raise LicenseValidationError("invalid_claims", "entitlement plan is invalid")
    status = payload.get("status")
    if status not in (_GRACE_STATUSES | _INACTIVE_STATUSES):
        raise LicenseValidationError("invalid_claims", "entitlement subscription status is invalid")
    revision = _strict_positive_int(payload.get("revision"), "revision", 2**63 - 1)
    catalog_hash = payload.get("catalog_sha256")
    device_key_hash = payload.get("device_public_key_sha256")
    if not isinstance(catalog_hash, str) or not _HEX_SHA256.fullmatch(catalog_hash):
        raise LicenseValidationError("invalid_claims", "entitlement catalog hash is invalid")
    if not isinstance(device_key_hash, str) or not _HEX_SHA256.fullmatch(device_key_hash):
        raise LicenseValidationError("invalid_claims", "entitlement device key hash is invalid")

    issued_at = _timestamp(payload.get("issued_at"), "issued_at")
    not_before = _timestamp(payload.get("not_before"), "not_before")
    expires_at = _timestamp(payload.get("expires_at"), "expires_at")
    grace_until = _timestamp(payload.get("grace_until"), "grace_until")
    if not issued_at <= not_before < expires_at <= grace_until:
        raise LicenseValidationError("invalid_claims", "entitlement time window is invalid")

    capabilities = _string_set(payload.get("capabilities"), "capabilities", _CAPABILITY_ID, 32)
    if not capabilities.issubset(_KNOWN_CAPABILITIES):
        raise LicenseValidationError("unknown_capability", "entitlement contains an unknown capability")

    return Entitlement(
        license_id=_safe_identifier(payload.get("license_id"), "license_id"),
        organization_id=_safe_identifier(payload.get("organization_id"), "organization_id"),
        site_id=_safe_identifier(payload.get("site_id"), "site_id"),
        device_id=_safe_identifier(payload.get("device_id"), "device_id"),
        device_public_key_sha256=device_key_hash,
        plan=plan,
        subscription_status=status,
        site_limit=_strict_positive_int(limits.get("sites"), "limits.sites"),
        stream_limit=_strict_positive_int(limits.get("streams"), "limits.streams"),
        distinct_function_limit=_strict_positive_int(
            limits.get("distinct_functions"), "limits.distinct_functions"
        ),
        function_ids=_string_set(
            payload.get("function_ids"),
            "function_ids",
            _FUNCTION_ID,
            _MAX_FUNCTION_GRANTS,
        ),
        capabilities=capabilities,
        catalog_sha256=catalog_hash,
        revision=revision,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        grace_until=grace_until,
    )


class EntitlementVerifier:
    """Verify compact EdDSA JWS documents and all appliance-local bindings."""

    def __init__(self, trusted_keys: Mapping[str, Ed25519PublicKey]):
        self._trusted_keys = dict(trusted_keys)

    def verify(
        self,
        token: str,
        *,
        catalog_hash: str,
        device_key_hash: str,
        now: int,
        device_id: str | None = None,
        site_id: str | None = None,
    ) -> VerifiedEntitlement:
        if not isinstance(token, str) or not token or len(token.encode("utf-8")) > _MAX_JWS_BYTES:
            raise LicenseValidationError("malformed_entitlement", "entitlement is missing or too large")
        parts = token.split(".")
        if len(parts) != 3:
            raise LicenseValidationError("malformed_entitlement", "entitlement must be a compact JWS")
        protected_segment, payload_segment, signature_segment = parts
        protected = _json_object(
            _b64url_decode(protected_segment, maximum=4096, code="malformed_entitlement"),
            code="malformed_entitlement",
        )
        if set(protected) != {"alg", "kid", "typ"} or protected.get("alg") != "EdDSA" or protected.get("typ") != _HEADER_TYPE:
            raise LicenseValidationError("invalid_header", "entitlement protected header is invalid")
        kid = protected.get("kid")
        if not isinstance(kid, str) or not _SAFE_ID.fullmatch(kid):
            raise LicenseValidationError("invalid_header", "entitlement key identifier is invalid")
        public_key = self._trusted_keys.get(kid)
        if public_key is None:
            raise LicenseValidationError("unknown_signing_key", "entitlement signing key is not trusted")
        signature = _b64url_decode(signature_segment, maximum=128, code="malformed_entitlement")
        if len(signature) != 64:
            raise LicenseValidationError("invalid_signature", "entitlement signature is invalid")
        try:
            public_key.verify(signature, f"{protected_segment}.{payload_segment}".encode("ascii"))
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise LicenseValidationError("invalid_signature", "entitlement signature is invalid") from exc

        payload = _json_object(
            _b64url_decode(payload_segment, maximum=48 * 1024, code="malformed_entitlement"),
            code="invalid_claims",
        )
        entitlement = _parse_claims(payload)
        if entitlement.catalog_sha256 != catalog_hash:
            raise LicenseValidationError("catalog_mismatch", "entitlement is for a different catalog release")
        if entitlement.device_public_key_sha256 != device_key_hash:
            raise LicenseValidationError("wrong_device_key", "entitlement is bound to another appliance key")
        if device_id is not None and entitlement.device_id != device_id:
            raise LicenseValidationError("wrong_device", "entitlement is bound to another appliance")
        if site_id is not None and entitlement.site_id != site_id:
            raise LicenseValidationError("wrong_site", "entitlement is bound to another site")
        if now < entitlement.not_before:
            raise LicenseValidationError("not_yet_valid", "entitlement is not yet valid")
        if entitlement.subscription_status in _INACTIVE_STATUSES:
            state = "invalid"
            reason = "subscription_inactive"
        elif entitlement.subscription_status == "past_due":
            state = "grace" if now <= entitlement.grace_until else "invalid"
            reason = "grace" if state == "grace" else "expired"
        elif now <= entitlement.expires_at:
            state = "current"
            reason = "authorized"
        elif now <= entitlement.grace_until:
            state = "grace"
            reason = "grace"
        else:
            state = "invalid"
            reason = "expired"
        return VerifiedEntitlement(entitlement=entitlement, state=state, reason=reason)


class DeviceIdentityStore:
    """Generate the appliance key locally and persist only signed device/site binding."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.private_key_path = directory / "device-private-key.pem"
        self.binding_path = directory / "device.json"

    def _private_key(self) -> Ed25519PrivateKey:
        if self.private_key_path.exists():
            try:
                if self.private_key_path.stat().st_size > 8192:
                    raise ValueError("oversized key")
                value = serialization.load_pem_private_key(self.private_key_path.read_bytes(), password=None)
            except (OSError, ValueError, TypeError) as exc:
                raise LicenseValidationError("device_identity_invalid", "local appliance identity is invalid") from exc
            if not isinstance(value, Ed25519PrivateKey):
                raise LicenseValidationError("device_identity_invalid", "local appliance identity is not Ed25519")
            os.chmod(self.private_key_path, 0o600)
            return value
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        _atomic_write(self.private_key_path, pem)
        return key

    def registration(self) -> dict[str, str]:
        raw = self._private_key().public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return {
            "algorithm": "Ed25519",
            "public_key": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
            "public_key_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def binding(self) -> dict[str, str] | None:
        if not self.binding_path.exists():
            return None
        try:
            if self.binding_path.stat().st_size > 4096:
                raise ValueError("oversized binding")
            payload = json.loads(self.binding_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise LicenseValidationError("device_binding_invalid", "local appliance binding is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {"schema", "device_id", "site_id"} or payload.get("schema") != _BINDING_SCHEMA:
            raise LicenseValidationError("device_binding_invalid", "local appliance binding is invalid")
        device_id = _safe_identifier(payload.get("device_id"), "device_id")
        site_id = _safe_identifier(payload.get("site_id"), "site_id")
        os.chmod(self.binding_path, 0o600)
        return {"device_id": device_id, "site_id": site_id}

    def bind(self, device_id: str, site_id: str) -> None:
        existing = self.binding()
        if existing and existing != {"device_id": device_id, "site_id": site_id}:
            code = "wrong_device" if existing["device_id"] != device_id else "wrong_site"
            raise LicenseValidationError(code, "entitlement does not match the enrolled appliance")
        payload = {"schema": _BINDING_SCHEMA, "device_id": device_id, "site_id": site_id}
        _atomic_write(
            self.binding_path,
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )


class LicenseService:
    """Deep local licensing module used by setup, runtime, status, and control seams."""

    def __init__(
        self,
        *,
        directory: str | Path,
        trusted_keys: Mapping[str, Ed25519PublicKey],
        catalog_sha256: str,
        installed_function_tiers: Mapping[str, str | None],
        clock: Callable[[], float] = time.time,
    ):
        if not _HEX_SHA256.fullmatch(catalog_sha256):
            raise ValueError("catalog_sha256 must be a lowercase SHA-256")
        self.directory = Path(directory)
        self.identity = DeviceIdentityStore(self.directory)
        self.verifier = EntitlementVerifier(trusted_keys)
        self.catalog_sha256 = catalog_sha256
        self.installed_function_tiers = dict(installed_function_tiers)
        self.clock = clock
        self.entitlement_path = self.directory / "entitlement.jws"
        self.state_path = self.directory / "state.json"
        self.lock_path = self.directory / ".license.lock"
        self._thread_lock = threading.RLock()

    @contextmanager
    def _exclusive(self):
        """Serialize entitlement and rollback-state operations across processes."""
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        with self._thread_lock:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def device_registration(self) -> dict[str, str]:
        with self._exclusive():
            return self.identity.registration()

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema": _STATE_SCHEMA,
            "max_revision": 0,
            "entitlement_sha256": "",
            "max_observed_at": 0,
            "last_authorized_mapping_sha256": "",
        }

    def _state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            if self.entitlement_path.exists() or self.identity.binding() is not None:
                raise LicenseValidationError("license_state_invalid", "license rollback state is missing")
            return self._default_state()
        try:
            if self.state_path.stat().st_size > 8192:
                raise ValueError("oversized state")
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise LicenseValidationError("license_state_invalid", "license rollback state is invalid") from exc
        expected = set(self._default_state())
        if not isinstance(state, dict) or set(state) != expected or state.get("schema") != _STATE_SCHEMA:
            raise LicenseValidationError("license_state_invalid", "license rollback state is invalid")
        if (
            isinstance(state.get("max_revision"), bool)
            or not isinstance(state.get("max_revision"), int)
            or state["max_revision"] < 0
            or isinstance(state.get("max_observed_at"), bool)
            or not isinstance(state.get("max_observed_at"), int)
            or state["max_observed_at"] < 0
        ):
            raise LicenseValidationError("license_state_invalid", "license rollback state is invalid")
        for field in ("entitlement_sha256", "last_authorized_mapping_sha256"):
            value = state.get(field)
            if not isinstance(value, str) or (value and not _HEX_SHA256.fullmatch(value)):
                raise LicenseValidationError("license_state_invalid", "license rollback state is invalid")
        os.chmod(self.state_path, 0o600)
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        _atomic_write(
            self.state_path,
            (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )

    def _now(self, state: dict[str, Any]) -> int:
        now = int(self.clock())
        if state["max_observed_at"] and now + _CLOCK_ROLLBACK_TOLERANCE_SECONDS < state["max_observed_at"]:
            raise LicenseValidationError("clock_rollback", "system clock moved behind the accepted license timeline")
        return now

    def _token(self) -> str:
        try:
            if not self.entitlement_path.is_file() or self.entitlement_path.stat().st_size > _MAX_JWS_BYTES:
                raise OSError("missing or oversized")
            token = self.entitlement_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise LicenseValidationError("entitlement_missing", "no signed entitlement is installed") from exc
        if not token:
            raise LicenseValidationError("entitlement_missing", "no signed entitlement is installed")
        os.chmod(self.entitlement_path, 0o600)
        return token

    def _verify_cached(self, state: dict[str, Any], now: int) -> VerifiedEntitlement:
        token = self._token()
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        if not state["entitlement_sha256"] or digest != state["entitlement_sha256"]:
            raise LicenseValidationError(
                "license_state_mismatch", "cached entitlement does not match accepted state"
            )
        binding = self.identity.binding()
        if binding is None:
            raise LicenseValidationError("device_binding_missing", "appliance enrollment is incomplete")
        registration = self.identity.registration()
        verified = self.verifier.verify(
            token,
            catalog_hash=self.catalog_sha256,
            device_key_hash=registration["public_key_sha256"],
            now=now,
            device_id=binding["device_id"],
            site_id=binding["site_id"],
        )
        if verified.entitlement.revision != state["max_revision"]:
            raise LicenseValidationError(
                "license_state_mismatch", "cached entitlement revision does not match accepted state"
            )
        return verified

    def _validate_plan_grants(self, entitlement: Entitlement) -> None:
        if entitlement.plan == "starter":
            if (
                entitlement.site_limit > 1
                or entitlement.stream_limit > 8
                or entitlement.distinct_function_limit > 5
            ):
                raise LicenseValidationError(
                    "plan_limit_violation", "starter entitlement exceeds signed plan ceilings"
                )
            disallowed = sorted(
                function_id
                for function_id in entitlement.function_ids
                if self.installed_function_tiers.get(function_id) in {"pro", "enterprise"}
            )
            if disallowed:
                raise LicenseValidationError(
                    "plan_tier_violation", "starter entitlement contains a non-starter catalog grant"
                )
        elif entitlement.plan == "professional":
            if (
                entitlement.site_limit > 1
                or entitlement.stream_limit > 24
                or entitlement.distinct_function_limit > 12
            ):
                raise LicenseValidationError(
                    "plan_limit_violation", "professional entitlement exceeds signed plan ceilings"
                )
            if any(
                self.installed_function_tiers.get(function_id) == "enterprise"
                for function_id in entitlement.function_ids
            ):
                raise LicenseValidationError(
                    "plan_tier_violation",
                    "professional entitlement contains an enterprise-only catalog grant",
                )

    def install_entitlement(self, token: str) -> dict[str, Any]:
        with self._exclusive():
            return self._install_entitlement_unlocked(token)

    def _install_entitlement_unlocked(self, token: str) -> dict[str, Any]:
        state = self._state()
        now = self._now(state)
        binding = self.identity.binding()
        registration = self.identity.registration()
        verified = self.verifier.verify(
            token,
            catalog_hash=self.catalog_sha256,
            device_key_hash=registration["public_key_sha256"],
            now=now,
            device_id=binding["device_id"] if binding else None,
            site_id=binding["site_id"] if binding else None,
        )
        self._validate_plan_grants(verified.entitlement)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        revision = verified.entitlement.revision
        if revision < state["max_revision"]:
            raise LicenseValidationError("revision_rollback", "entitlement revision is older than accepted state")
        if revision == state["max_revision"] and state["entitlement_sha256"] not in {"", digest}:
            raise LicenseValidationError("revision_conflict", "entitlement revision conflicts with accepted state")

        state.update(
            {
                "max_revision": max(state["max_revision"], revision),
                "entitlement_sha256": digest,
                "max_observed_at": max(state["max_observed_at"], now),
            }
        )
        # Persist rollback state first. A crash during the following writes fails
        # closed and permits only an identical/higher signed retry.
        self._write_state(state)
        _atomic_write(self.entitlement_path, (token + "\n").encode("ascii"))
        self.identity.bind(verified.entitlement.device_id, verified.entitlement.site_id)
        return self._status_unlocked()

    @staticmethod
    def _usage(config: dict[str, Any]) -> tuple[int, frozenset[str], str]:
        cameras = config.get("cameras") if isinstance(config, dict) else None
        if not isinstance(cameras, list) or len(cameras) > 100_000:
            raise LicenseValidationError("invalid_configuration", "camera configuration is invalid")
        seen_cameras: set[str] = set()
        functions: set[str] = set()
        active_stream_count = 0
        mapping: list[dict[str, Any]] = []
        for camera in cameras:
            if not isinstance(camera, dict):
                raise LicenseValidationError("invalid_configuration", "camera configuration is invalid")
            camera_id = camera.get("id")
            detectors = camera.get("detectors", [])
            if not isinstance(camera_id, str) or not _SAFE_ID.fullmatch(camera_id) or camera_id in seen_cameras:
                raise LicenseValidationError("invalid_configuration", "camera configuration contains invalid IDs")
            if not isinstance(detectors, list) or len(detectors) > 256:
                raise LicenseValidationError("invalid_configuration", "detector configuration is invalid")
            seen_cameras.add(camera_id)
            detector_set: set[str] = set()
            for detector_id in detectors:
                if (
                    not isinstance(detector_id, str)
                    or not _FUNCTION_ID.fullmatch(detector_id)
                    or detector_id in detector_set
                ):
                    raise LicenseValidationError("invalid_configuration", "detector configuration is invalid")
                detector_set.add(detector_id)
                functions.add(detector_id)
            if detector_set:
                active_stream_count += 1
            mapping.append({"camera_id": camera_id, "function_ids": sorted(detector_set)})
        try:
            canonical_config = json.dumps(
                config,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise LicenseValidationError(
                "invalid_configuration", "camera configuration is not canonical JSON"
            ) from exc
        fingerprint = hashlib.sha256(canonical_config).hexdigest()
        return active_stream_count, frozenset(functions), fingerprint

    @staticmethod
    def _disabled(config: dict[str, Any]) -> dict[str, Any]:
        effective = copy.deepcopy(config) if isinstance(config, dict) else {"cameras": []}
        cameras = effective.get("cameras")
        if not isinstance(cameras, list):
            effective["cameras"] = []
            return effective
        for camera in cameras:
            if isinstance(camera, dict):
                camera["detectors"] = []
        return effective

    def _denied(
        self,
        config: dict[str, Any],
        *,
        state: str,
        reason: str,
        stream_count: int,
        distinct_count: int,
        grants: frozenset[str] = frozenset(),
    ) -> RuntimeAuthorization:
        return RuntimeAuthorization(
            authorized=False,
            state=state,
            reason=reason,
            effective_config=self._disabled(config),
            stream_count=stream_count,
            distinct_function_count=distinct_count,
            granted_function_ids=grants,
        )

    def authorize_configuration(
        self, config: dict[str, Any], *, record_current: bool = True
    ) -> RuntimeAuthorization:
        with self._exclusive():
            return self._authorize_configuration_unlocked(
                config, record_current=record_current
            )

    def _authorize_configuration_unlocked(
        self, config: dict[str, Any], *, record_current: bool = True
    ) -> RuntimeAuthorization:
        try:
            stream_count, functions, mapping_hash = self._usage(config)
        except LicenseValidationError as exc:
            return self._denied(
                config,
                state="invalid",
                reason=exc.code,
                stream_count=0,
                distinct_count=0,
            )
        if not functions:
            return RuntimeAuthorization(
                authorized=True,
                state=self._status_unlocked()["state"],
                reason="no_paid_functions",
                effective_config=copy.deepcopy(config),
                stream_count=stream_count,
                distinct_function_count=0,
                granted_function_ids=frozenset(),
            )
        try:
            state = self._state()
            now = self._now(state)
            verified = self._verify_cached(state, now)
            self._validate_plan_grants(verified.entitlement)
        except LicenseValidationError as exc:
            return self._denied(
                config,
                state="unlicensed" if exc.code == "entitlement_missing" else "invalid",
                reason=exc.code,
                stream_count=stream_count,
                distinct_count=len(functions),
            )

        entitlement = verified.entitlement
        if verified.state == "invalid":
            return self._denied(
                config,
                state="invalid",
                reason=verified.reason,
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if entitlement.site_limit < 1:
            return self._denied(
                config,
                state="invalid",
                reason="site_limit",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if stream_count > entitlement.stream_limit:
            return self._denied(
                config,
                state=verified.state,
                reason="stream_limit",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if len(functions) > entitlement.distinct_function_limit:
            return self._denied(
                config,
                state=verified.state,
                reason="distinct_function_limit",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if not functions.issubset(entitlement.function_ids):
            return self._denied(
                config,
                state=verified.state,
                reason="function_not_granted",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if not functions.issubset(self.installed_function_tiers):
            return self._denied(
                config,
                state=verified.state,
                reason="update_required",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )
        if verified.state == "grace" and state["last_authorized_mapping_sha256"] != mapping_hash:
            return self._denied(
                config,
                state="grace",
                reason="grace_configuration_changed",
                stream_count=stream_count,
                distinct_count=len(functions),
                grants=entitlement.function_ids,
            )

        if record_current:
            state["max_observed_at"] = max(state["max_observed_at"], now)
            if verified.state == "current":
                state["last_authorized_mapping_sha256"] = mapping_hash
            self._write_state(state)
        return RuntimeAuthorization(
            authorized=True,
            state=verified.state,
            reason="authorized",
            effective_config=copy.deepcopy(config),
            stream_count=stream_count,
            distinct_function_count=len(functions),
            granted_function_ids=entitlement.function_ids,
        )

    def validate_configuration(self, config: dict[str, Any]) -> RuntimeAuthorization:
        return self.authorize_configuration(config, record_current=False)

    def _verified_status(self) -> tuple[VerifiedEntitlement, dict[str, Any], int]:
        state = self._state()
        now = self._now(state)
        verified = self._verify_cached(state, now)
        self._validate_plan_grants(verified.entitlement)
        state["max_observed_at"] = max(state["max_observed_at"], now)
        self._write_state(state)
        return verified, state, now

    def status(self) -> dict[str, Any]:
        with self._exclusive():
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        try:
            verified, _state, _now = self._verified_status()
        except LicenseValidationError as exc:
            state = "unlicensed" if exc.code == "entitlement_missing" else "invalid"
            return {
                "state": state,
                "reason": exc.code,
                "current": False,
                "grace": False,
                "paid_runtime_authorized": False,
                "function_grant_count": 0,
                "capability_grant_count": 0,
            }
        entitlement = verified.entitlement
        return {
            "state": verified.state,
            "reason": verified.reason,
            "current": verified.state == "current",
            "grace": verified.state == "grace",
            "paid_runtime_authorized": verified.state in {"current", "grace"},
            "license_id": entitlement.license_id,
            "organization_id": entitlement.organization_id,
            "site_id": entitlement.site_id,
            "device_id": entitlement.device_id,
            "plan": entitlement.plan,
            "subscription_status": entitlement.subscription_status,
            "revision": entitlement.revision,
            "expires_at": datetime.fromtimestamp(entitlement.expires_at, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "grace_until": datetime.fromtimestamp(entitlement.grace_until, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "limits": {
                "sites": entitlement.site_limit,
                "streams": entitlement.stream_limit,
                "distinct_functions": entitlement.distinct_function_limit,
            },
            "function_grant_count": len(entitlement.function_ids),
            "capability_grant_count": len(entitlement.capabilities),
        }

    def allows_function(self, function_id: str) -> bool:
        if not isinstance(function_id, str) or not _FUNCTION_ID.fullmatch(function_id):
            return False
        with self._exclusive():
            try:
                verified, _state, _now = self._verified_status()
                self._validate_plan_grants(verified.entitlement)
            except LicenseValidationError:
                return False
            return (
                verified.state in {"current", "grace"}
                and function_id in verified.entitlement.function_ids
                and function_id in self.installed_function_tiers
            )

    def allows_capability(self, capability: str) -> bool:
        if not isinstance(capability, str) or not _CAPABILITY_ID.fullmatch(capability):
            return False
        with self._exclusive():
            try:
                verified, _state, _now = self._verified_status()
            except LicenseValidationError:
                return False
            return (
                verified.state in {"current", "grace"}
                and capability in verified.entitlement.capabilities
            )


def load_trusted_keys(path: str | Path) -> dict[str, Ed25519PublicKey]:
    """Load the public verification-key set baked into the signed image."""
    key_path = Path(path)
    try:
        if not key_path.is_file() or key_path.stat().st_size > 64 * 1024:
            raise OSError("missing or oversized key set")
        payload = json.loads(key_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise LicenseValidationError("trust_store_invalid", "entitlement trust store is unavailable") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "keys"} or payload.get("schema") != "nexus.entitlement-keys/v1" or not isinstance(payload.get("keys"), dict):
        raise LicenseValidationError("trust_store_invalid", "entitlement trust store is invalid")
    result: dict[str, Ed25519PublicKey] = {}
    for kid, encoded in payload["keys"].items():
        if not isinstance(kid, str) or not _SAFE_ID.fullmatch(kid) or not isinstance(encoded, str):
            raise LicenseValidationError("trust_store_invalid", "entitlement trust store is invalid")
        raw = _b64url_decode(encoded, maximum=128, code="trust_store_invalid")
        if len(raw) != 32:
            raise LicenseValidationError("trust_store_invalid", "entitlement trust store is invalid")
        try:
            result[kid] = Ed25519PublicKey.from_public_bytes(raw)
        except ValueError as exc:
            raise LicenseValidationError("trust_store_invalid", "entitlement trust store is invalid") from exc
    return result
