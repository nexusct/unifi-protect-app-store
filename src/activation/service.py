"""Transactional local configuration activation with rollback and redacted audit."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import platform
import secrets
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import yaml

_PLAN_SCHEMA = "nexus.activation-plan/v1"
_STATE_SCHEMA = "nexus.activation-state/v1"
_MAX_PLAN_BYTES = 2 * 1024 * 1024
_MAX_CONFIG_BYTES = 2 * 1024 * 1024


class ActivationError(RuntimeError):
    """A stable, non-secret activation failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ActivationError("invalid_configuration", "configuration is not canonical JSON") from exc


def _config_bytes(config: dict[str, Any]) -> bytes:
    try:
        rendered = yaml.safe_dump(config, sort_keys=False, allow_unicode=True).encode("utf-8")
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise ActivationError("invalid_configuration", "configuration cannot be rendered safely") from exc
    if len(rendered) > _MAX_CONFIG_BYTES:
        raise ActivationError("invalid_configuration", "configuration exceeds the local size limit")
    return rendered


class ActivationService:
    """Plan and atomically apply one licensed local configuration revision."""

    def __init__(
        self,
        *,
        directory: str | Path,
        config_path: str | Path,
        license_service,
        clock: Callable[[], float] = time.time,
        platform_probe: Callable[[], tuple[str, str]] = lambda: (sys.platform, platform.machine()),
        reload_callback: Callable[[Path], None] | None = None,
        readiness_check: Callable[[], bool] | None = None,
        max_revisions: int = 5,
    ):
        self.directory = Path(directory)
        self.config_path = Path(config_path)
        self.license_service = license_service
        self.clock = clock
        self.platform_probe = platform_probe
        self.reload_callback = reload_callback or (lambda _path: None)
        # Applying without a real readiness adapter must fail closed.
        self.readiness_check = readiness_check or (lambda: False)
        self.max_revisions = max(1, min(int(max_revisions), 100))
        self.plans_directory = self.directory / "plans"
        self.revisions_directory = self.directory / "revisions"
        self.state_path = self.directory / "state.json"
        self.audit_path = self.directory / "audit.jsonl"
        self.lock_path = self.directory / ".activation.lock"
        self._thread_lock = threading.RLock()

    @contextmanager
    def _exclusive(self):
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

    def _require_platform(self) -> None:
        system, machine = self.platform_probe()
        if str(system).lower() != "linux" or str(machine).lower() not in {"x86_64", "amd64"}:
            raise ActivationError(
                "unsupported_platform",
                "this activation release supports Linux AMD64 only",
            )

    @staticmethod
    def _plan_digest(plan_id: str) -> str:
        if not isinstance(plan_id, str) or not 32 <= len(plan_id) <= 256:
            raise ActivationError("plan_missing", "activation plan does not exist")
        return hashlib.sha256(plan_id.encode("utf-8")).hexdigest()

    def _plan_path(self, plan_id: str) -> Path:
        return self.plans_directory / f"{self._plan_digest(plan_id)}.json"

    def _state(self) -> dict[str, Any]:
        default = {
            "schema": _STATE_SCHEMA,
            "max_revision": 0,
            "active_revision": 0,
            "active_config_sha256": "",
        }
        if not self.state_path.exists():
            return default
        try:
            if self.state_path.stat().st_size > 8192:
                raise ValueError("oversized state")
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise ActivationError("activation_state_invalid", "activation state is invalid") from exc
        if not isinstance(value, dict) or set(value) != set(default) or value.get("schema") != _STATE_SCHEMA:
            raise ActivationError("activation_state_invalid", "activation state is invalid")
        for field in ("max_revision", "active_revision"):
            if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 0:
                raise ActivationError("activation_state_invalid", "activation state is invalid")
        digest = value["active_config_sha256"]
        if not isinstance(digest, str) or (digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest))):
            raise ActivationError("activation_state_invalid", "activation state is invalid")
        os.chmod(self.state_path, 0o600)
        return value

    def _write_state(self, state: dict[str, Any]) -> None:
        _atomic_write(self.state_path, _canonical_json(state) + b"\n")

    def _audit(self, event: str, *, plan_digest: str, revision: int = 0, reason: str = "") -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "nexus.activation-audit/v1",
            "at": int(self.clock()),
            "event": event,
            "plan_sha256": plan_digest,
            "revision": revision,
            "reason": reason,
        }
        line = _canonical_json(record) + b"\n"
        descriptor = os.open(self.audit_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _summary(config: dict[str, Any]) -> dict[str, Any]:
        cameras = config.get("cameras", []) if isinstance(config, dict) else []
        functions = sorted(
            {
                detector
                for camera in cameras
                if isinstance(camera, dict)
                for detector in camera.get("detectors", [])
                if isinstance(detector, str)
            }
        )
        return {
            "camera_count": len(cameras) if isinstance(cameras, list) else 0,
            "function_ids": functions,
            "distinct_function_count": len(functions),
        }

    def plan(self, requested_config: dict[str, Any], *, ttl_seconds: int = 300) -> dict[str, Any]:
        self._require_platform()
        ttl = int(ttl_seconds)
        if not 5 <= ttl <= 900:
            raise ActivationError("invalid_plan_ttl", "activation plan TTL is invalid")
        authorization = self.license_service.validate_configuration(requested_config)
        if not getattr(authorization, "authorized", False):
            reason = str(getattr(authorization, "reason", "license_denied"))
            raise ActivationError(reason, "signed entitlement does not authorize this configuration")
        config = copy.deepcopy(requested_config)
        canonical = _canonical_json(config)
        if len(canonical) > _MAX_CONFIG_BYTES:
            raise ActivationError("invalid_configuration", "configuration exceeds the local size limit")
        plan_id = secrets.token_urlsafe(32)
        plan_digest = self._plan_digest(plan_id)
        now = int(self.clock())
        document = {
            "schema": _PLAN_SCHEMA,
            "plan_sha256": plan_digest,
            "created_at": now,
            "expires_at": now + ttl,
            "config_sha256": hashlib.sha256(canonical).hexdigest(),
            "config": config,
        }
        with self._exclusive():
            path = self._plan_path(plan_id)
            if path.exists():
                raise ActivationError("plan_conflict", "activation plan identifier collided")
            _atomic_write(path, _canonical_json(document) + b"\n")
            self._audit("plan_created", plan_digest=plan_digest)
        return {
            "plan_id": plan_id,
            "expires_at": document["expires_at"],
            "summary": self._summary(config),
        }

    def _load_plan(self, plan_id: str) -> tuple[Path, dict[str, Any], str]:
        plan_digest = self._plan_digest(plan_id)
        path = self._plan_path(plan_id)
        if not path.is_file():
            raise ActivationError("plan_missing", "activation plan does not exist")
        try:
            if path.stat().st_size > _MAX_PLAN_BYTES:
                raise OSError("oversized plan")
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise ActivationError("plan_invalid", "activation plan is invalid") from exc
        expected = {
            "schema",
            "plan_sha256",
            "created_at",
            "expires_at",
            "config_sha256",
            "config",
        }
        if not isinstance(document, dict) or set(document) != expected or document.get("schema") != _PLAN_SCHEMA:
            raise ActivationError("plan_invalid", "activation plan is invalid")
        if document.get("plan_sha256") != plan_digest or not isinstance(document.get("config"), dict):
            raise ActivationError("plan_invalid", "activation plan is invalid")
        canonical = _canonical_json(document["config"])
        if hashlib.sha256(canonical).hexdigest() != document.get("config_sha256"):
            raise ActivationError("plan_invalid", "activation plan was altered")
        for field in ("created_at", "expires_at"):
            if isinstance(document.get(field), bool) or not isinstance(document.get(field), int):
                raise ActivationError("plan_invalid", "activation plan is invalid")
        os.chmod(path, 0o600)
        return path, document, plan_digest

    def _restore(self, previous: bytes | None) -> None:
        if previous is None:
            self.config_path.unlink(missing_ok=True)
        else:
            _atomic_write(self.config_path, previous)
        self.reload_callback(self.config_path)

    def _prune_revisions(self) -> None:
        self.revisions_directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.revisions_directory, 0o700)
        revisions = sorted(path for path in self.revisions_directory.glob("*.yaml") if path.is_file())
        for path in revisions[:-self.max_revisions]:
            path.unlink(missing_ok=True)

    def apply(self, plan_id: str) -> dict[str, Any]:
        self._require_platform()
        with self._exclusive():
            path, document, plan_digest = self._load_plan(plan_id)
            now = int(self.clock())
            if now > document["expires_at"]:
                path.unlink(missing_ok=True)
                self._audit("plan_rejected", plan_digest=plan_digest, reason="plan_expired")
                raise ActivationError("plan_expired", "activation plan expired")

            consumed_path = path.with_suffix(".applying")
            os.replace(path, consumed_path)
            config = document["config"]
            authorization = self.license_service.validate_configuration(config)
            if not getattr(authorization, "authorized", False):
                consumed_path.unlink(missing_ok=True)
                reason = str(getattr(authorization, "reason", "license_denied"))
                self._audit("plan_rejected", plan_digest=plan_digest, reason=reason)
                raise ActivationError(reason, "signed entitlement no longer authorizes this plan")

            state = self._state()
            revision = state["max_revision"] + 1
            candidate = _config_bytes(config)
            previous = self.config_path.read_bytes() if self.config_path.is_file() else None
            previous_active_revision = state["active_revision"]
            try:
                _atomic_write(self.config_path, candidate)
                self.reload_callback(self.config_path)
                if self.readiness_check() is not True:
                    raise ActivationError("readiness_failed", "candidate configuration did not become ready")
            except Exception as exc:
                failed_path = self.revisions_directory / f"{revision:020d}-failed.yaml"
                _atomic_write(failed_path, candidate)
                self._restore(previous)
                state.update({"max_revision": revision, "active_revision": previous_active_revision})
                self._write_state(state)
                self._prune_revisions()
                consumed_path.unlink(missing_ok=True)
                self._audit(
                    "apply_failed",
                    plan_digest=plan_digest,
                    revision=revision,
                    reason="readiness_failed",
                )
                if isinstance(exc, ActivationError):
                    raise
                raise ActivationError("readiness_failed", "candidate configuration failed to apply") from exc

            good_path = self.revisions_directory / f"{revision:020d}-good.yaml"
            _atomic_write(good_path, candidate)
            digest = hashlib.sha256(candidate).hexdigest()
            state.update(
                {
                    "max_revision": revision,
                    "active_revision": revision,
                    "active_config_sha256": digest,
                }
            )
            self._write_state(state)
            self._prune_revisions()
            consumed_path.unlink(missing_ok=True)
            self._audit("apply_succeeded", plan_digest=plan_digest, revision=revision)
            return {
                "plan_id": plan_id,
                "applied": True,
                "revision": revision,
                "config_sha256": digest,
            }

    def status(self) -> dict[str, Any]:
        with self._exclusive():
            state = self._state()
            return {
                "max_revision": state["max_revision"],
                "active_revision": state["active_revision"],
                "configured": self.config_path.is_file(),
            }
