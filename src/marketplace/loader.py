"""Marketplace loader: walk functions/, read manifests, build catalog + registry."""
import importlib.util
import json
import logging
from pathlib import Path

from .contract import ID_PATTERN, MarketplaceFunction, validate_manifest
from .api_functions import APIFunctionInventoryError, function_class_for, load_api_function_manifests

log = logging.getLogger("marketplace.loader")
DEFAULT_FUNCTIONS_DIR = Path(__file__).parent / "functions"
FUNCTIONS_DIR = DEFAULT_FUNCTIONS_DIR
ACTIVE_FUNCTIONS_PATH = Path(__file__).parent / "active-function-ids.json"

REGISTRY = {}   # id -> {"manifest": dict, "cls": class}


def load_active_function_ids(path: Path, available_ids: set[str]) -> tuple[str, ...]:
    """Load the exact 80 retained + 20 new commercial catalog selection."""
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ValueError("active selection is missing or oversized")
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("active selection is invalid") from exc
    expected = {"schema", "retained_existing_ids", "vendor_inspired_ids"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("active selection has invalid fields")
    if document.get("schema") != "nexus.marketplace-selection/v1":
        raise ValueError("active selection has unsupported schema")
    retained = document.get("retained_existing_ids")
    vendor = document.get("vendor_inspired_ids")
    if not isinstance(retained, list) or len(retained) != 80:
        raise ValueError("active selection requires exactly 80 retained IDs")
    if not isinstance(vendor, list) or len(vendor) != 20:
        raise ValueError("active selection requires exactly 20 vendor-inspired IDs")
    selected = retained + vendor
    if any(
        not isinstance(function_id, str)
        or len(function_id) > 80
        or ID_PATTERN.fullmatch(function_id) is None
        for function_id in selected
    ):
        raise ValueError("active selection contains an invalid function ID")
    if len(set(selected)) != len(selected):
        raise ValueError("active selection contains a duplicate function ID")
    unknown = sorted(set(selected) - set(available_ids))
    if unknown:
        raise ValueError(f"active selection contains unknown function IDs: {unknown}")
    return tuple(selected)


def load_all(*, include_archived=False):
    """Load executable contracts, publishing only the explicit active 100 by default.

    ``include_archived=True`` is an audit/migration interface. Archived contracts
    remain importable source but cannot be instantiated through the default
    production registry.
    """
    REGISTRY.clear()
    errors = {}
    sources = {}
    for path in sorted(FUNCTIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"marketplace.functions.{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            manifest = getattr(mod, "MANIFEST", None)
            cls = getattr(mod, "Function", None)
            if not manifest or not cls:
                errors[path.stem] = "missing MANIFEST or Function"
                continue
            if not isinstance(cls, type) or not issubclass(cls, MarketplaceFunction):
                errors[path.stem] = "Function must subclass MarketplaceFunction"
                continue
            errs = validate_manifest(manifest)
            if errs:
                errors[path.stem] = "; ".join(errs)
                continue
            function_id = manifest["id"]
            if function_id in REGISTRY:
                errors[path.stem] = f"duplicate id {function_id!r}; already defined by {sources[function_id]}"
                continue
            cls.name = function_id
            REGISTRY[function_id] = {"manifest": manifest, "cls": cls}
            sources[function_id] = path.name
        except Exception as exc:
            errors[path.stem] = str(exc)
    # Test/plugin callers may temporarily point FUNCTIONS_DIR at an isolated
    # registry. The product API inventory belongs only to the canonical tree.
    if FUNCTIONS_DIR.resolve() == DEFAULT_FUNCTIONS_DIR.resolve():
        try:
            for manifest in load_api_function_manifests():
                function_id = manifest["id"]
                if function_id in REGISTRY:
                    errors[f"api:{function_id}"] = (
                        f"duplicate id {function_id!r}; already defined by {sources[function_id]}"
                    )
                    continue
                cls = function_class_for(manifest)
                REGISTRY[function_id] = {"manifest": manifest, "cls": cls}
                sources[function_id] = "api_functions.json"
        except APIFunctionInventoryError as exc:
            errors["api_functions"] = str(exc)
    canonical_tree = FUNCTIONS_DIR.resolve() == DEFAULT_FUNCTIONS_DIR.resolve()
    if canonical_tree and not include_archived and not errors:
        try:
            selected_ids = load_active_function_ids(
                ACTIVE_FUNCTIONS_PATH, set(REGISTRY)
            )
        except ValueError as exc:
            errors["active_selection"] = str(exc)
            REGISTRY.clear()
        else:
            selected = {function_id: REGISTRY[function_id] for function_id in selected_ids}
            REGISTRY.clear()
            REGISTRY.update(selected)
    if errors:
        for k, v in errors.items():
            log.error("function %s failed to load: %s", k, v)
    return dict(REGISTRY), errors


def catalog():
    """Storefront view: one row per function."""
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "tagline": m["tagline"],
            "category": m["category"],
            "tier": m["tier"],
            "requires_gpu": m.get("requires_gpu", True),
            "config_keys": sorted((m.get("config_schema") or {}).keys()),
            "config_schema": dict(m.get("config_schema") or {}),
            "api": dict(m["api"]) if m.get("api") else None,
        }
        for m in (entry["manifest"] for entry in REGISTRY.values())
    ]


def instantiate(function_id: str, settings: dict):
    entry = REGISTRY.get(function_id)
    if not entry:
        raise KeyError(f"unknown marketplace function: {function_id}")
    return entry["cls"](settings)
