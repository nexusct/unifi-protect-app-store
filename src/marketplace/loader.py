"""Marketplace loader: walk functions/, read manifests, build catalog + registry."""
import importlib.util
import logging
from pathlib import Path

from .contract import validate_manifest

log = logging.getLogger("marketplace.loader")
FUNCTIONS_DIR = Path(__file__).parent / "functions"

REGISTRY = {}   # id -> {"manifest": dict, "cls": class}


def load_all():
    REGISTRY.clear()
    errors = {}
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
            errs = validate_manifest(manifest)
            if errs:
                errors[path.stem] = "; ".join(errs)
                continue
            REGISTRY[manifest["id"]] = {"manifest": manifest, "cls": cls}
        except Exception as exc:
            errors[path.stem] = str(exc)
    if errors:
        for k, v in errors.items():
            log.error("function %s failed to load: %s", k, v)
    return REGISTRY, errors


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
        }
        for m in (entry["manifest"] for entry in REGISTRY.values())
    ]


def instantiate(function_id: str, settings: dict):
    entry = REGISTRY.get(function_id)
    if not entry:
        raise KeyError(f"unknown marketplace function: {function_id}")
    return entry["cls"](settings)
