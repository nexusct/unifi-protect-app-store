"""Production assembly for the local signed-entitlement module."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Iterable

from .licensing import LicenseService, LicenseValidationError, catalog_sha256, load_trusted_keys

_FUNCTION_ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG = _ROOT / "storefront" / "catalog.json"
_DEFAULT_TRUST_STORE = _ROOT / "config" / "trusted-entitlement-keys.json"

# Core detector contracts are part of the entitlement compatibility catalog even
# though they are not storefront products. Bump contract_version whenever an
# enforcement-relevant core configuration/capability contract changes.
CORE_FUNCTIONS = (
    {"id": "fall", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "bed_exit", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "weapon", "tier": "enterprise", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "ppe", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "near_miss", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "elopement", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "alpr", "tier": "enterprise", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "video_search", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "tailgating", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
    {"id": "smoke_flame", "tier": "pro", "kind": "core", "requires_gpu": True, "contract_version": 1},
)


def _catalog(path: Path) -> list[dict]:
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise OSError("missing or oversized catalog")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise LicenseValidationError("catalog_invalid", "installed marketplace catalog is unavailable") from exc
    if not isinstance(payload, list) or len(payload) > 512:
        raise LicenseValidationError("catalog_invalid", "installed marketplace catalog is invalid")
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            raise LicenseValidationError("catalog_invalid", "installed marketplace catalog is invalid")
        function_id = row.get("id")
        tier = row.get("tier")
        if (
            not isinstance(function_id, str)
            or not _FUNCTION_ID.fullmatch(function_id)
            or function_id in seen
            or tier not in {"starter", "pro", "enterprise"}
        ):
            raise LicenseValidationError("catalog_invalid", "installed marketplace catalog is invalid")
        seen.add(function_id)
    return payload


def build_license_service(
    installed_function_ids: Iterable[str],
    *,
    directory: str | Path | None = None,
    trust_store_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    clock: Callable[[], float] = time.time,
) -> LicenseService:
    """Assemble licensing from the signed image catalog and public trust anchors."""
    selected_catalog_path = Path(
        catalog_path or os.environ.get("VISION_CATALOG_PATH", str(_DEFAULT_CATALOG))
    )
    selected_trust_store = Path(
        trust_store_path
        or os.environ.get("VISION_ENTITLEMENT_TRUST_STORE", str(_DEFAULT_TRUST_STORE))
    )
    selected_directory = Path(
        directory or os.environ.get("VISION_LICENSE_DIR", "/config/licensing")
    )
    catalog = _catalog(selected_catalog_path)
    core_ids = {row["id"] for row in CORE_FUNCTIONS}
    marketplace_ids = {row["id"] for row in catalog}
    if core_ids.intersection(marketplace_ids):
        raise LicenseValidationError("catalog_invalid", "core and marketplace catalog IDs collide")
    enforcement_catalog = [*catalog, *CORE_FUNCTIONS]
    catalog_tiers = {row["id"]: row["tier"] for row in enforcement_catalog}
    installed = set(installed_function_ids)
    if any(not isinstance(function_id, str) or not _FUNCTION_ID.fullmatch(function_id) for function_id in installed):
        raise LicenseValidationError("runtime_registry_invalid", "installed detector registry is invalid")
    unknown = installed.difference(catalog_tiers)
    if unknown:
        raise LicenseValidationError("runtime_registry_invalid", "installed detector is absent from enforcement catalog")
    tiers = {function_id: catalog_tiers[function_id] for function_id in installed}
    return LicenseService(
        directory=selected_directory,
        trusted_keys=load_trusted_keys(selected_trust_store),
        catalog_sha256=catalog_sha256(enforcement_catalog),
        installed_function_tiers=tiers,
        clock=clock,
    )
