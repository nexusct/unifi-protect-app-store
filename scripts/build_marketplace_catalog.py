#!/usr/bin/env python3
"""Build the static marketplace catalog from literal MANIFEST declarations."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_DIR = ROOT / "src" / "marketplace" / "functions"
CATALOG_JSON = ROOT / "storefront" / "catalog.json"
CATALOG_JS = ROOT / "storefront" / "catalog.js"
ACTIVE_FUNCTIONS = ROOT / "src" / "marketplace" / "active-function-ids.json"

APPROVED_FUNCTION_BASES = {
    "MarketplaceFunction",
    "DetectorAdapterFunction",
    "PlateWatchlistFunction",
    "VehicleAttributeFunction",
    "VehicleZoneDwellFunction",
    "StationaryVehicleFunction",
    "CountHoldFunction",
    "UnusualDwellBaselineFunction",
    "QueueAbandonmentFunction",
    "ForkliftProximityFunction",
    "PerimeterClimbFunction",
    "VehicleWrongWayFunction",
    "RollingCountAnomalyFunction",
    "FloorAppearanceFunction",
    "MotionBaselineFunction",
    "ObjectRemovalFunction",
    "AssemblySequenceFunction",
    "PackageLabelFunction",
}

GEOMETRY_DESCRIPTION = re.compile(
    r"\bpolygons?\b|(?:\b2\b|\btwo\b)[ -]point.*\bline\b",
    re.IGNORECASE,
)

sys.path.insert(0, str(ROOT / "src"))
from marketplace.contract import validate_manifest  # noqa: E402
from marketplace.api_functions import load_api_function_manifests  # noqa: E402
from marketplace.loader import load_active_function_ids  # noqa: E402


def manifest_from_file(path: Path) -> dict:
    """Read a literal MANIFEST without importing or executing the module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MANIFEST" for target in node.targets
        ):
            assignments.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MANIFEST":
            assignments.append(node.value)

    if len(assignments) != 1:
        raise ValueError(f"expected one literal MANIFEST assignment, found {len(assignments)}")
    manifest = ast.literal_eval(assignments[0])
    if not isinstance(manifest, dict):
        raise ValueError("MANIFEST must evaluate to a dict")
    function_classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Function"]
    if len(function_classes) != 1:
        raise ValueError(f"expected one Function class, found {len(function_classes)}")
    base_names = {
        base.id if isinstance(base, ast.Name) else base.attr
        for base in function_classes[0].bases
        if isinstance(base, (ast.Name, ast.Attribute))
    }
    if len(base_names) != 1 or not base_names.issubset(APPROVED_FUNCTION_BASES):
        raise ValueError("Function must directly subclass an approved marketplace base")
    return manifest


def literal_camera_zone_map(path: Path):
    """Return an optional literal CAMERA_ZONES mapping without executing code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CAMERA_ZONES"
            for target in node.targets
        ):
            assignments.append(node.value)
    if not assignments:
        return None
    if len(assignments) != 1:
        raise ValueError("expected at most one literal CAMERA_ZONES assignment")
    mapping = ast.literal_eval(assignments[0])
    if not isinstance(mapping, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in mapping.items()
    ):
        raise ValueError("CAMERA_ZONES must be a string-to-string dict")
    return mapping


def _normalized_geometry_key(key: str) -> str:
    for suffix in ("_zones", "_zone", "_lines", "_line", "_polygon", "_roi"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def camera_zone_map_from_file(path: Path, schema: dict) -> dict[str, str]:
    """Map manifest geometry settings to the camera.zones keys used at runtime."""
    declared_mapping = literal_camera_zone_map(path)
    if declared_mapping is not None:
        geometry_keys = {
            key for key, description in schema.items()
            if GEOMETRY_DESCRIPTION.search(description)
        }
        if set(declared_mapping) != geometry_keys:
            raise ValueError(
                "CAMERA_ZONES must map every and only geometry config key: "
                f"expected={sorted(geometry_keys)}, actual={sorted(declared_mapping)}"
            )
        if any(not value or value == "*" for value in declared_mapping.values()):
            raise ValueError("CAMERA_ZONES values must name concrete runtime camera zones")
        return declared_mapping
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function_class = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Function"),
        None,
    )
    if function_class is None:
        raise ValueError("missing Function class")

    aliases = set()
    uses_camera_zones = False
    for node in ast.walk(function_class):
        if not isinstance(node, ast.Assign):
            continue
        expression = ast.unparse(node.value)
        if 'camera.get("zones")' not in expression and "camera.get('zones')" not in expression:
            continue
        uses_camera_zones = True
        aliases.update(target.id for target in node.targets if isinstance(target, ast.Name))

    lookups = []
    for node in ast.walk(function_class):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        owner = ast.unparse(node.func.value)
        direct = 'camera.get("zones")' in owner or "camera.get('zones')" in owner
        if direct or owner in aliases:
            lookups.append((node.lineno, node.args[0].value))
            uses_camera_zones = True
    runtime_keys = [key for _line, key in sorted(set(lookups))]

    geometry_keys = [
        key for key, description in schema.items()
        if GEOMETRY_DESCRIPTION.search(description)
    ]
    mapping = {}
    used_runtime_keys = set()

    for key in geometry_keys:
        if key in runtime_keys:
            mapping[key] = key
            used_runtime_keys.add(key)

    for key in geometry_keys:
        if key in mapping:
            continue
        normalized = _normalized_geometry_key(key)
        candidates = [
            runtime_key for runtime_key in runtime_keys
            if runtime_key not in used_runtime_keys
            and (
                _normalized_geometry_key(runtime_key) == normalized
                or normalized in runtime_key.split("_")
            )
        ]
        if len(candidates) == 1:
            mapping[key] = candidates[0]
            used_runtime_keys.add(candidates[0])

    for key in geometry_keys:
        if key in mapping:
            continue
        remaining = [runtime_key for runtime_key in runtime_keys if runtime_key not in used_runtime_keys]
        description = schema[key]
        is_line = "line" in description.casefold() and "polygon" not in description.casefold()
        candidates = [runtime_key for runtime_key in remaining if ("line" in runtime_key) == is_line]
        if len(candidates) == 1:
            mapping[key] = candidates[0]
            used_runtime_keys.add(candidates[0])

    remaining_geometry = [key for key in geometry_keys if key not in mapping]
    remaining_runtime = [key for key in runtime_keys if key not in used_runtime_keys]
    if len(remaining_geometry) == len(remaining_runtime) == 1:
        mapping[remaining_geometry[0]] = remaining_runtime[0]
        used_runtime_keys.add(remaining_runtime[0])

    if geometry_keys == ["zones"] and not runtime_keys and uses_camera_zones:
        mapping["zones"] = "*"

    unmapped_geometry = sorted(set(geometry_keys) - set(mapping))
    unmapped_runtime = sorted(set(runtime_keys) - used_runtime_keys)
    if unmapped_geometry or unmapped_runtime:
        raise ValueError(
            "camera geometry contract mismatch: "
            f"unmapped manifest keys={unmapped_geometry}, runtime camera.zones keys={unmapped_runtime}"
        )
    return mapping


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    rows = []
    sources = {}
    errors = []

    for path in sorted(FUNCTIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            manifest = manifest_from_file(path)
            manifest_errors = validate_manifest(manifest)
            if manifest_errors:
                raise ValueError("; ".join(manifest_errors))
            function_id = manifest["id"]
            if function_id in sources:
                raise ValueError(f"duplicate id {function_id!r}; already defined by {sources[function_id]}")
            sources[function_id] = path.name
            schema = dict(manifest.get("config_schema") or {})
            camera_zones = camera_zone_map_from_file(path, schema)
            rows.append(
                {
                    "id": function_id,
                    "name": manifest["name"],
                    "tagline": manifest["tagline"],
                    "category": manifest["category"],
                    "tier": manifest["tier"],
                    "requires_gpu": manifest.get("requires_gpu", True),
                    "config_keys": sorted(schema),
                    "config_schema": schema,
                    "camera_zones": camera_zones,
                    "setting_keys": sorted(set(schema) - set(camera_zones)),
                }
            )
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    try:
        for manifest in load_api_function_manifests():
            function_id = manifest["id"]
            if function_id in sources:
                raise ValueError(
                    f"duplicate id {function_id!r}; already defined by {sources[function_id]}"
                )
            sources[function_id] = "api_functions.json"
            schema = dict(manifest.get("config_schema") or {})
            rows.append(
                {
                    "id": function_id,
                    "name": manifest["name"],
                    "tagline": manifest["tagline"],
                    "category": manifest["category"],
                    "tier": manifest["tier"],
                    "requires_gpu": manifest.get("requires_gpu", False),
                    "config_keys": sorted(schema),
                    "config_schema": schema,
                    "camera_zones": {},
                    "setting_keys": sorted(schema),
                    "api": dict(manifest["api"]),
                    "api_surface": manifest["api"]["surface"],
                    "api_primitive": manifest["api"]["primitive"],
                    "api_runner": manifest["api"]["runner"],
                    "api_control": manifest["api"]["control"],
                }
            )
    except Exception as exc:
        errors.append(f"api_functions.json: {exc}")

    if errors:
        raise SystemExit("Catalog build failed:\n- " + "\n- ".join(errors))
    if not rows:
        raise SystemExit("Catalog build failed: no marketplace manifests found")

    try:
        selected_ids = load_active_function_ids(
            ACTIVE_FUNCTIONS, {row["id"] for row in rows}
        )
    except ValueError as exc:
        raise SystemExit(f"Catalog build failed: {exc}") from exc
    rows_by_id = {row["id"]: row for row in rows}
    rows = [rows_by_id[function_id] for function_id in selected_ids]

    rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    payload = json.dumps(rows, indent=1, ensure_ascii=True) + "\n"
    script = (
        "// Generated by scripts/build_marketplace_catalog.py — do not edit by hand.\n"
        "// Inlined so the storefront works from file://, static subpaths, and FastAPI.\n"
        f"window.CATALOG_DATA = {payload.rstrip()};\n"
    )
    atomic_write(CATALOG_JSON, payload)
    atomic_write(CATALOG_JS, script)
    print(f"Generated {len(rows)} marketplace entries in catalog.json and catalog.js")


if __name__ == "__main__":
    main()
