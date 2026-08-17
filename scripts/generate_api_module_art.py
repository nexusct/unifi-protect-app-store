#!/usr/bin/env python3
"""Generate deterministic module art and scene records for API functions only.

The original 130 commissioned WebPs are immutable inputs. This generator adds
service-specific transparent vector-style WebPs for the 101 Protect and 20
Access declarations and merges their prompt records into the existing plan.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "storefront" / "catalog.json"
ART_DIR = ROOT / "assets" / "module-art"
SCENE_PLAN_PATH = ART_DIR / "scene-plan.json"
SIZE = 320
SCALE = 4
CANVAS = SIZE * SCALE

NAVY = "#01183E"
BLUE = "#0559D5"
BRIGHT = "#18A0FB"
SLATE = "#5F718B"
PALE = "#D7E9FB"
MINT = "#4CC9A7"
AMBER = "#F0A43A"
RED = "#D94A59"

PROFILE_SCENES = {
    "camera_inventory": (
        "A compact UniFi security camera beside a small fleet of camera silhouettes",
        "Local Protect camera inventory represented as physical devices rather than a software screen",
    ),
    "event_metrics": (
        "A UniFi security camera projecting one bounded event pulse into a local record capsule",
        "Protect event activity contained on the on-premises appliance",
    ),
    "stream_quality": (
        "A security camera lens aimed through a clean rectangular video frame and signal trace",
        "Locally decoded RTSP video quality inspection",
    ),
    "scene_quality": (
        "A security camera lens inspecting a framed scene with a calibrated visual signal",
        "Local RTSP scene-quality measurement without identity recognition",
    ),
    "snapshot_capture": (
        "A security camera placing one still frame into a sealed local snapshot tray",
        "Scheduled or operator-requested local snapshot capture",
    ),
    "snapshot_governance": (
        "A stack of local snapshot frames beside a shield, clock, or storage gauge",
        "On-appliance snapshot retention and integrity governance",
    ),
    "clip_export": (
        "A security camera feeding a short film strip into a sealed evidence capsule",
        "Bounded local Protect clip export with explicit evidence limits",
    ),
    "event_clip": (
        "A security camera joining one event pulse to a short sealed film strip",
        "Event-scoped local Protect evidence export with bounded pre-roll and post-roll",
    ),
    "clip_governance": (
        "A sealed local film strip beside a shield, clock, or storage gauge",
        "On-appliance Protect clip retention, integrity, and export governance",
    ),
    "clip_postprocess": (
        "A sealed local film strip feeding one small review frame",
        "On-appliance Protect clip post-processing without external video transfer",
    ),
    "log_event": (
        "A secured doorway receiving one credential event pulse",
        "Local UniFi Access developer-log observation",
    ),
    "log_aggregate": (
        "A secured doorway beside a bounded group of event tokens and a compact signal arc",
        "Local UniFi Access event aggregation by door and reporting window",
    ),
    "log_audit": (
        "A secured doorway beside a shielded Access event token and review marker",
        "Local UniFi Access developer-log audit without identity inference",
    ),
    "log_inventory": (
        "A secured doorway beside a small roster of distinct physical event tokens",
        "Local UniFi Access door and event-type inventory",
    ),
    "log_quality": (
        "A secured doorway receiving a measured event pulse through a quality gauge",
        "Local UniFi Access developer-log delivery and consistency review",
    ),
    "log_sequence": (
        "A secured doorway followed by an ordered chain of event tokens",
        "Local UniFi Access event-sequence review with bounded timing",
    ),
    "log_window": (
        "A secured doorway beside first and last event tokens held inside a clock arc",
        "Local UniFi Access event-window review",
    ),
    "audited_unlock": (
        "A secured doorway with a key request held inside a shielded approval ring",
        "Explicit operator-requested UniFi Access control with separate authorization",
    ),
}

COMPOSITIONS = (
    "Camera or doorway anchors the lower left while the measured signal rises toward the upper right",
    "Primary device fills the center with the bounded signal nested in a smaller upper corner",
    "Two physical objects balance across the centerline with the observed signal bridging them",
    "Primary device sits high and the local evidence or event artifact rests securely below",
    "A diagonal device-to-signal flow fills the square while preserving generous transparent margins",
    "Concentric device and signal forms create a compact centered emblem without a containing tile",
)


def atomic_write_text(path: Path, value: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_inputs():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or len(catalog) != 251:
        raise SystemExit("expected the exact 251-entry generated catalog")
    api_rows = [row for row in catalog if isinstance(row, dict) and isinstance(row.get("api"), dict)]
    if len(api_rows) != 121:
        raise SystemExit("expected exactly 121 declarative API functions")
    if sum(row["api"]["surface"] == "protect" for row in api_rows) != 101:
        raise SystemExit("expected exactly 101 Protect API functions")
    if sum(row["api"]["surface"] == "access" for row in api_rows) != 20:
        raise SystemExit("expected exactly 20 Access API functions")
    plan = json.loads(SCENE_PLAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise SystemExit("scene plan must be an object")
    api_ids = {row["id"] for row in api_rows}
    legacy_ids = {row["id"] for row in catalog} - api_ids
    existing_webps = {path.stem for path in ART_DIR.glob("*.webp")}
    if len(legacy_ids) != 130 or not legacy_ids.issubset(existing_webps):
        raise SystemExit("all 130 original WebPs must exist before additive generation")
    if not legacy_ids.issubset(plan):
        raise SystemExit("all 130 original scene records must exist before additive generation")
    return api_rows, plan, legacy_ids


def scene_for(row: dict) -> dict[str, str]:
    binding = row["api"]
    profile = binding["profile"]
    subject, context = PROFILE_SCENES[profile]
    concepts = [
        token
        for token in row["id"].split("-")
        if token not in {"protect", "access", "rtsp", "event", "camera", "snapshot", "clip", "export"}
    ]
    concept = " ".join(concepts[:4]) or profile.replace("_", " ")
    digest = hashlib.sha256(row["id"].encode()).digest()
    color = ("blue", "cyan", "mint", "amber")[digest[0] % 4]
    signal = f"A distinct {color} geometric pulse marks the bounded {concept} observation without words or numerals"
    return {
        "subject": subject,
        "context": context,
        "signal": signal,
        "composition": COMPOSITIONS[digest[1] % len(COMPOSITIONS)],
    }


def sc(value: float) -> int:
    return round(value * SCALE)


def line(draw, points, *, fill, width=4, joint="curve"):
    draw.line([(sc(x), sc(y)) for x, y in points], fill=fill, width=sc(width), joint=joint)


def rounded(draw, box, radius, *, fill=None, outline=None, width=1):
    draw.rounded_rectangle(tuple(sc(value) for value in box), radius=sc(radius), fill=fill, outline=outline, width=sc(width))


def ellipse(draw, box, *, fill=None, outline=None, width=1):
    draw.ellipse(tuple(sc(value) for value in box), fill=fill, outline=outline, width=sc(width))


def polygon(draw, points, *, fill=None, outline=None, width=1):
    scaled = [(sc(x), sc(y)) for x, y in points]
    draw.polygon(scaled, fill=fill)
    if outline:
        draw.line(scaled + [scaled[0]], fill=outline, width=sc(width), joint="curve")


def camera(draw, x, y, scale=1.0, accent=BLUE):
    def p(value):
        return value * scale
    rounded(draw, (x, y + p(13), x + p(94), y + p(71)), p(15), fill=NAVY)
    polygon(
        draw,
        [(x + p(18), y + p(14)), (x + p(29), y), (x + p(61), y), (x + p(73), y + p(14))],
        fill=SLATE,
    )
    ellipse(draw, (x + p(26), y + p(20), x + p(82), y + p(76)), fill=PALE)
    ellipse(draw, (x + p(35), y + p(29), x + p(73), y + p(67)), fill=accent)
    ellipse(draw, (x + p(47), y + p(41), x + p(61), y + p(55)), fill=NAVY)
    ellipse(draw, (x + p(51), y + p(44), x + p(56), y + p(49)), fill="#FFFFFF")


def doorway(draw, x, y, scale=1.0, accent=BLUE):
    w, h = 82 * scale, 116 * scale
    rounded(draw, (x, y, x + w, y + h), 9 * scale, fill=NAVY)
    rounded(draw, (x + 13 * scale, y + 13 * scale, x + 68 * scale, y + h), 5 * scale, fill=PALE)
    polygon(
        draw,
        [(x + 22 * scale, y + 24 * scale), (x + 60 * scale, y + 18 * scale), (x + 60 * scale, y + h - 7 * scale), (x + 22 * scale, y + h - 2 * scale)],
        fill=accent,
    )
    ellipse(draw, (x + 48 * scale, y + 66 * scale, x + 55 * scale, y + 73 * scale), fill="#FFFFFF")


def shield(draw, cx, cy, size, accent=MINT):
    s = size
    polygon(
        draw,
        [(cx, cy - s * .52), (cx + s * .45, cy - s * .34), (cx + s * .38, cy + s * .25), (cx, cy + s * .52), (cx - s * .38, cy + s * .25), (cx - s * .45, cy - s * .34)],
        fill=accent,
        outline=NAVY,
        width=3,
    )
    line(draw, [(cx - s * .19, cy), (cx - s * .03, cy + s * .16), (cx + s * .24, cy - s * .16)], fill="#FFFFFF", width=4)


def film(draw, x, y, w=105, h=72, accent=BLUE):
    rounded(draw, (x, y, x + w, y + h), 12, fill=NAVY)
    rounded(draw, (x + 16, y + 14, x + w - 16, y + h - 14), 7, fill=accent)
    for px in range(int(x + 9), int(x + w - 6), 20):
        rounded(draw, (px, y + 5, px + 8, y + 11), 2, fill=PALE)
        rounded(draw, (px, y + h - 11, px + 8, y + h - 5), 2, fill=PALE)


def frame(draw, x, y, w=100, h=78, accent=BLUE):
    rounded(draw, (x, y, x + w, y + h), 10, fill=NAVY)
    rounded(draw, (x + 10, y + 10, x + w - 10, y + h - 10), 6, fill=PALE)
    polygon(draw, [(x + 18, y + h - 18), (x + 42, y + 35), (x + 60, y + 54), (x + 74, y + 39), (x + w - 18, y + h - 18)], fill=accent)
    ellipse(draw, (x + w - 34, y + 18, x + w - 22, y + 30), fill=AMBER)


def pulse(draw, x, y, w=105, accent=BRIGHT, phase=0):
    points = [(x, y), (x + 18, y), (x + 31, y - 22 - phase), (x + 46, y + 28), (x + 62, y - 10), (x + 77, y), (x + w, y)]
    line(draw, points, fill=accent, width=6)
    for px, py in (points[0], points[-1]):
        ellipse(draw, (px - 5, py - 5, px + 5, py + 5), fill=accent)


def clock(draw, cx, cy, size=54, accent=AMBER):
    ellipse(draw, (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2), fill=PALE, outline=NAVY, width=4)
    line(draw, [(cx, cy), (cx, cy - size * .27)], fill=accent, width=5)
    line(draw, [(cx, cy), (cx + size * .22, cy + size * .13)], fill=accent, width=5)


def event_tokens(draw, x, y, count, accent):
    for index in range(count):
        offset = index * 18
        rounded(draw, (x + offset, y - index * 4, x + offset + 42, y + 31 - index * 4), 10, fill=accent if index == count - 1 else PALE, outline=NAVY, width=3)
        ellipse(draw, (x + offset + 12, y + 9 - index * 4, x + offset + 22, y + 19 - index * 4), fill=NAVY)


def signal_color(digest: bytes) -> str:
    return (BLUE, BRIGHT, MINT, AMBER)[digest[2] % 4]


def draw_art(row: dict) -> Image.Image:
    digest = hashlib.sha256(row["id"].encode()).digest()
    accent = signal_color(digest)
    profile = row["api"]["profile"]
    variant = digest[0] % 6
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # A low-opacity directional signal replaces generic card backgrounds while
    # preserving transparent corners and the unboxed visual language.
    angle = (digest[3] / 255) * math.tau
    cx, cy = 160 + math.cos(angle) * 12, 160 + math.sin(angle) * 10
    ellipse(draw, (cx - 76, cy - 76, cx + 76, cy + 76), fill=(*ImageColor.getrgb(PALE), 118))

    clip_profiles = {"clip_export", "event_clip", "clip_governance", "clip_postprocess"}
    access_log_profiles = {"log_event", "log_aggregate", "log_audit", "log_inventory", "log_quality", "log_sequence", "log_window"}
    if profile in {"camera_inventory", "event_metrics", "stream_quality", "scene_quality"}:
        camera(draw, 48 if variant % 2 == 0 else 42, 108, 1.15, accent)
    elif profile in {"snapshot_capture", "snapshot_governance"} | clip_profiles:
        camera(draw, 38, 126, .9, accent)
    else:
        doorway(draw, 42 if variant % 2 == 0 else 50, 91, 1.12, accent)

    if profile == "camera_inventory":
        count = 2 + digest[4] % 3
        for index in range(count):
            x = 162 + (index % 2) * 51
            y = 101 + (index // 2) * 63
            camera(draw, x, y, .46, (BLUE, BRIGHT, MINT)[index % 3])
        pulse(draw, 156, 238, 98, accent, digest[5] % 8)
    elif profile == "event_metrics":
        event_tokens(draw, 160, 113 + variant * 3, 2 + digest[4] % 3, accent)
        pulse(draw, 153, 226, 112, accent, digest[5] % 10)
    elif profile in {"stream_quality", "scene_quality"}:
        frame(draw, 163, 98, 111, 87, accent)
        pulse(draw, 157, 231, 115, accent, digest[5] % 12)
        if any(token in row["id"] for token in ("blur", "focus", "noise", "pixel", "block")):
            for index in range(3 + digest[6] % 4):
                x = 181 + ((digest[7 + index] * 41) // 255)
                y = 117 + ((digest[11 + index] * 44) // 255)
                ellipse(draw, (x, y, x + 6 + index, y + 6 + index), fill=SLATE)
    elif profile in {"snapshot_capture", "snapshot_governance"}:
        frame(draw, 143, 92, 125, 98, accent)
        if profile == "snapshot_governance":
            if any(token in row["id"] for token in ("retention", "age", "storage", "budget")):
                clock(draw, 225, 222, 58, accent)
            else:
                shield(draw, 225, 221, 58, accent)
        else:
            pulse(draw, 150, 230, 112, accent, digest[5] % 8)
    elif profile in clip_profiles:
        film(draw, 144, 101, 127, 88, accent)
        if any(token in row["id"] for token in ("checksum", "integrity", "validation")):
            shield(draw, 224, 224, 55, MINT)
        elif any(token in row["id"] for token in ("latency", "duration", "queue", "retry")):
            clock(draw, 226, 222, 56, AMBER)
        else:
            pulse(draw, 151, 232, 112, accent, digest[5] % 8)
    elif profile == "audited_unlock":
        shield(draw, 215, 143, 82, MINT)
        # Physical key silhouette, not a text glyph.
        ellipse(draw, (176, 213, 206, 243), fill=AMBER, outline=NAVY, width=4)
        line(draw, [(203, 228), (262, 228), (262, 215), (247, 215), (247, 228)], fill=NAVY, width=9)
    elif profile in access_log_profiles:
        event_tokens(draw, 154, 112, 2 + digest[4] % 4, accent)
        pulse(draw, 151, 229, 117, accent, digest[5] % 9)
        if any(token in row["id"] for token in ("lag", "duration", "timing", "first", "last")):
            clock(draw, 232, 179, 45, AMBER)

    # Unique functional marker: bounded observed nodes, varied from the ID hash.
    nodes = 2 + digest[15] % 4
    for index in range(nodes):
        theta = (index / nodes) * math.tau + angle
        radius = 105 + digest[16 + index] % 16
        x = 160 + math.cos(theta) * radius
        y = 160 + math.sin(theta) * radius
        ellipse(draw, (x - 5, y - 5, x + 5, y + 5), fill=accent)

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


# Pillow exposes ImageColor separately; importing here keeps the drawing helpers compact.
from PIL import ImageColor  # noqa: E402


def save_webp(path: Path, image: Image.Image) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".webp")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, "WEBP", lossless=True, method=6, exact=True)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    api_rows, plan, legacy_ids = load_inputs()
    for row in sorted(api_rows, key=lambda item: item["id"]):
        plan[row["id"]] = scene_for(row)
        save_webp(ART_DIR / f"{row['id']}.webp", draw_art(row))
    catalog_ids = legacy_ids | {row["id"] for row in api_rows}
    if set(plan) != catalog_ids:
        extras = set(plan) - catalog_ids
        missing = catalog_ids - set(plan)
        raise SystemExit(f"scene plan mismatch: extras={sorted(extras)} missing={sorted(missing)}")
    atomic_write_text(
        SCENE_PLAN_PATH,
        json.dumps({key: plan[key] for key in sorted(plan)}, indent=2, ensure_ascii=True) + "\n",
    )
    print(f"Generated {len(api_rows)} additive API WebPs and merged {len(plan)} scene records")


if __name__ == "__main__":
    main()
