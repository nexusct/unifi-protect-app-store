#!/usr/bin/env python3
"""Generate one original SVG app-icon image for every marketplace module."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "storefront" / "catalog.json"
OUTPUT = ROOT / "assets" / "icons"
ID_PATTERN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")

# Original geometric line-art symbols. All use a 24x24 coordinate system.
SYMBOLS = {
    "shield": '<path d="M12 3 20 6v5c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V6Z"/><path d="m8.5 12 2.3 2.3 4.8-5"/>',
    "camera": '<rect x="3" y="6" width="18" height="13" rx="3"/><path d="m8 6 1.5-3h5L16 6"/><circle cx="12" cy="12.5" r="3.5"/>',
    "car": '<path d="M3 14.5 5.5 9h13l2.5 5.5v3H3Z"/><path d="M6 9 8 5h8l2 4"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "truck": '<path d="M3 6h11v11H3Z"/><path d="M14 10h4l3 3v4h-7Z"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    "door": '<path d="M5 21V3h13v18"/><path d="M8 21V6l7-1v16"/><circle cx="13" cy="13" r=".7" fill="white" stroke="none"/>',
    "flame": '<path d="M13 2c1 5-3 6-1 10 1-2 3-3 4-5 3 3 4 6 3 9-1 4-4 6-8 6s-7-3-7-7c0-4 3-7 7-11 0 3 1 4 2 5"/>',
    "medical": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M7 12h10"/>',
    "waves": '<path d="M3 8c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 3-2"/><path d="M3 13c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 3-2"/><path d="M3 18c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 3-2"/>',
    "people": '<circle cx="9" cy="7" r="3"/><circle cx="17" cy="9" r="2.3"/><path d="M3 20c.5-5 2.5-7 6-7s5.5 2 6 7"/><path d="M14 14c3.5 0 5.5 2 6 6"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "person": '<circle cx="12" cy="6" r="3"/><path d="M5 21c.7-6 3-9 7-9s6.3 3 7 9"/>',
    "route": '<path d="M5 19c0-7 3-7 7-7s7 0 7-7"/><path d="m15 5 4-3 3 4"/><circle cx="5" cy="19" r="2"/>',
    "package": '<path d="m4 7 8-4 8 4v10l-8 4-8-4Z"/><path d="m4 7 8 4 8-4M12 11v10M8 5l8 4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
    "check": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3.5h6M8 12l2.5 2.5L16 9"/>',
    "animal": '<circle cx="7" cy="8" r="2"/><circle cx="17" cy="8" r="2"/><circle cx="5" cy="13" r="2"/><circle cx="19" cy="13" r="2"/><path d="M8 18c0-3 1.8-5 4-5s4 2 4 5c0 2-1.7 3-4 3s-4-1-4-3Z"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/><circle cx="12" cy="12" r="7"/>',
    "building": '<path d="M4 21V5l8-3 8 3v16M8 7h2M14 7h2M8 11h2M14 11h2M8 15h2M14 15h2M10 21v-3h4v3"/>',
    "cart": '<path d="M3 4h2l2 11h11l2-7H7"/><circle cx="9" cy="19" r="1.7"/><circle cx="17" cy="19" r="1.7"/>',
    "plate": '<rect x="3" y="6" width="18" height="12" rx="3"/><path d="M7 10h10M7 14h6"/><circle cx="17" cy="14" r="1"/>',
    "alert": '<path d="M12 3 2.5 20h19Z"/><path d="M12 9v5M12 17.5v.5"/>',
    "scan": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M7 12h10"/>',
}

KEYWORDS = [
    ("flame", ("fire", "smoke", "flame")),
    ("medical", ("bed", "mri", "clinical", "pharmacy", "specimen", "hygiene")),
    ("waves", ("pool", "water", "leak", "splash", "flood")),
    ("truck", ("truck", "trailer", "dock", "forklift", "freight", "conveyor", "pallet")),
    ("plate", ("plate", "license", "alpr")),
    ("camera", ("camera", "tamper", "coverage")),
    ("door", ("door", "exit", "access", "entry", "gate", "tailgate")),
    ("route", ("route", "path", "wrong-way", "wrong way", "curbside", "pickup", "arrival")),
    ("package", ("inventory", "stock", "object", "package", "shelf")),
    ("cart", ("cart", "retail", "vending")),
    ("animal", ("kennel", "livestock", "animal")),
    ("gear", ("machine", "equipment", "pump", "construction", "jam")),
    ("clock", ("time", "timer", "dwell", "cycle", "after-hours", "overnight")),
    ("check", ("audit", "log", "verification", "check", "compliance", "rule", "ratio")),
    ("alert", ("alert", "warning", "distress", "aggression", "breach", "blocked", "drive-off")),
    ("scan", ("scan", "search", "detail", "qc", "damage", "inspection", "detect")),
    ("car", ("car", "vehicle", "parking", "drive-thru", "charger", "service lane", "stall", "lot")),
    ("people", ("queue", "line", "waiting", "crowd", "occupancy", "attendance", "capacity", "flow", "count")),
    ("person", ("visitor", "resident", "child", "person", "staff", "driver")),
    ("building", ("room", "building", "pavilion", "facility", "floor")),
    ("eye", ("visual", "view", "privacy", "loiter", "monitor", "watch")),
]

CATEGORY_FALLBACKS = {
    "Automotive & Parking": "car",
    "Compliance": "check",
    "Healthcare & Senior Living": "medical",
    "Intelligence": "scan",
    "Manufacturing & Warehouse": "gear",
    "People & Safety": "people",
    "Property & Liability": "building",
    "Retail & QSR": "cart",
    "Security & Access": "shield",
}


def motif_for(item: dict) -> str:
    haystack = " ".join((item["name"], item["tagline"])).lower()
    for motif, words in KEYWORDS:
        if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", haystack) for word in words):
            return motif
    return CATEGORY_FALLBACKS.get(item["category"], "shield")


def svg_for(item: dict) -> tuple[str, str]:
    motif = motif_for(item)
    symbol = SYMBOLS[motif].replace('fill="white"', 'fill="#01183E"')
    title = escape(item["name"])
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" role="img" aria-labelledby="title">
  <title id="title">{title}</title>
  <circle cx="76" cy="20" r="8" fill="#006FFF" opacity=".12"/>
  <path d="M20 77h56" fill="none" stroke="#01183E" stroke-width="2" stroke-linecap="round" opacity=".18"/>
  <g transform="translate(12 12) scale(3)" fill="none" stroke="#0559D5" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">
    {symbol}
  </g>
</svg>
'''
    return svg, motif


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
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or not catalog:
        raise SystemExit("Icon generation failed: catalog must be a non-empty list")

    rendered = {}
    manifest = {}
    seen = set()
    for item in catalog:
        function_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(function_id, str) or len(function_id) > 80 or not ID_PATTERN.fullmatch(function_id):
            raise SystemExit(f"Icon generation failed: unsafe module id {function_id!r}")
        if function_id in seen:
            raise SystemExit(f"Icon generation failed: duplicate module id {function_id!r}")
        seen.add(function_id)
        svg, motif = svg_for(item)
        filename = f"{function_id}.svg"
        rendered[filename] = svg
        manifest[function_id] = {"file": filename, "motif": motif, "style": "transparent-line"}

    fallback, _ = svg_for({
        "id": "nexus-vision-module-fallback",
        "name": "Nexus Vision module",
        "tagline": "Local video intelligence function",
        "category": "Security & Access",
    })
    rendered["_fallback.svg"] = fallback

    OUTPUT.mkdir(parents=True, exist_ok=True)
    expected = set(rendered)
    for filename, svg in rendered.items():
        atomic_write(OUTPUT / filename, svg)
    atomic_write(OUTPUT / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    for stale in OUTPUT.glob("*.svg"):
        if stale.name not in expected:
            stale.unlink()
    print(f"Generated {len(manifest)} marketplace icon images plus fallback in {OUTPUT}")


if __name__ == "__main__":
    main()
