#!/usr/bin/env python3
"""Maintain the marketplace module art set.

Module art is the per-module illustration shown on storefront cards. It is an
optional enhancement layered over the always-present SVG icon set: a module with
art in ``assets/module-art/<id>.webp`` renders that image, and every other module
falls back to ``assets/icons/<id>.svg``. Nothing here is required for the
storefront to render correctly.

The images themselves are produced out-of-band by an image model. This script
does not call one; it owns the reproducible record (prompt + seed per module)
and regenerates ``assets/module-art/manifest.js`` from the files actually on
disk, so dropping a new ``.webp`` in and re-running is the whole workflow.

Usage:
    python3 scripts/generate_module_art.py           # rebuild manifest, report status
    python3 scripts/generate_module_art.py --prompts # print prompts still to generate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "storefront" / "catalog.json"
OUTPUT = ROOT / "assets" / "module-art"
MANIFEST = "manifest.js"
PROMPTS = "prompts.json"
SCENE_PLAN = OUTPUT / "scene-plan.json"

# Shared trailing style clause. Keeping it identical across every prompt is what
# holds the set together visually; edit it only if the whole set is regenerated.
STYLE = (
    "Pure pictorial marketplace icon scene; absolutely no typography or UI text. "
    "No text-bearing signs, posters, documents, screens, charts, labels, letters, digits, "
    "logos, or watermark; any necessary panel or card is a blank geometric shape. "
    "Premium flat editorial vector illustration with only two or three large focal objects, "
    "thick clean geometric shapes, centered composition filling about 80 percent of the square, "
    "high contrast and recognizable at 88 pixels. Use deep Nexus navy, Ubiquiti blue, and "
    "medium slate only; do not use white as an object fill. Pure flat white contiguous background "
    "intended for automatic transparency removal. No colored square or tile, no gradient background, "
    "no border, no frame, and no decorative scenery."
)


def safe_stem(value: str) -> bool:
    """Reject anything that could escape the output directory."""
    return bool(value) and "/" not in value and "\\" not in value and value not in {".", ".."}


def load_catalog() -> dict[str, dict]:
    rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        sys.exit("catalog must be a non-empty list")
    catalog = {row["id"]: row for row in rows}
    if len(catalog) != len(rows):
        sys.exit("catalog contains duplicate module ids")
    return catalog


def load_scene_plan(catalog_ids: set[str]) -> dict[str, dict[str, str]]:
    if not SCENE_PLAN.is_file():
        sys.exit(f"scene plan is missing: {SCENE_PLAN}")
    raw = json.loads(SCENE_PLAN.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != catalog_ids:
        sys.exit("scene plan ids must exactly match the catalog")
    required = {"subject", "context", "signal", "composition"}
    for module_id, scene in raw.items():
        if not isinstance(scene, dict) or set(scene) != required:
            sys.exit(f"invalid scene plan fields for {module_id}")
        if not all(isinstance(value, str) and value.strip() for value in scene.values()):
            sys.exit(f"scene plan values must be non-empty strings for {module_id}")
    return raw


def prompt_registry(
    catalog: dict[str, dict],
    scene_plan: dict[str, dict[str, str]],
) -> dict[str, dict[str, int | str]]:
    registry: dict[str, dict[str, int | str]] = {}
    used_seeds: set[int] = set()
    for module_id in sorted(catalog):
        scene = scene_plan[module_id]
        seed = int.from_bytes(hashlib.sha256(module_id.encode()).digest()[:4], "big")
        while seed in used_seeds:
            seed = (seed + 1) % (2**32)
        used_seeds.add(seed)
        prompt = (
            f"Subject: {scene['subject']}. "
            f"Context: {scene['context']}. "
            f"Signal: {scene['signal']}. "
            f"Composition: {scene['composition']}. "
            f"{STYLE}"
        )
        registry[module_id] = {"seed": seed, "prompt": prompt}
    return registry


def present_art(catalog_ids: set[str]) -> list[str]:
    if not OUTPUT.is_dir():
        return []
    found = []
    for path in sorted(OUTPUT.glob("*.webp")):
        stem = path.stem
        if not safe_stem(stem):
            sys.exit(f"unsafe art filename: {path.name}")
        if stem not in catalog_ids:
            sys.exit(f"art file does not match any catalog module: {path.name}")
        found.append(stem)
    return found


def write_manifest(ids: list[str], registry: dict[str, dict[str, int | str]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(sorted(ids), indent=2, ensure_ascii=True)
    text = (
        "/* Generated by scripts/generate_module_art.py - do not edit by hand.\n"
        "   Modules listed here render illustrated art; all others fall back to\n"
        "   their assets/icons/<id>.svg icon. */\n"
        f"window.MODULE_ART = {body};\n"
    )
    (OUTPUT / MANIFEST).write_text(text, encoding="utf-8")
    (OUTPUT / PROMPTS).write_text(
        json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", action="store_true", help="print prompts for art not yet generated")
    args = parser.parse_args()

    catalog = load_catalog()
    catalog_ids = set(catalog)
    scene_plan = load_scene_plan(catalog_ids)
    registry = prompt_registry(catalog, scene_plan)

    have = present_art(catalog_ids)
    write_manifest(have, registry)

    planned = sorted(catalog_ids)
    missing = [module_id for module_id in planned if module_id not in set(have)]

    if args.prompts:
        for module_id in missing:
            entry = registry[module_id]
            print(f"--- {module_id} (seed {entry['seed']})")
            print(f"{entry['prompt']}\n")
        return

    print(f"catalog modules      : {len(catalog_ids)}")
    print(f"planned art          : {len(planned)}")
    print(f"art on disk          : {len(have)}")
    print(f"still to generate    : {len(missing)}")
    if missing:
        print("  " + "\n  ".join(missing))
    print(f"wrote {(OUTPUT / MANIFEST).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
