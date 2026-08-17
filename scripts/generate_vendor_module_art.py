#!/usr/bin/env python3
"""Generate and reconcile artwork for the 20 vendor-pattern marketplace plugins.

Retired top-level WebPs are moved into ``assets/module-art/archive/webp`` rather
than deleted. Existing selected artwork is preserved byte-for-byte. This script
creates only the 20 independently implemented plugin illustrations, rewrites the
active 100-entry scene plan, and refreshes the art manifest/prompt registry.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "storefront" / "catalog.json"
SELECTION_PATH = ROOT / "src" / "marketplace" / "active-function-ids.json"
ART_DIR = ROOT / "assets" / "module-art"
SCENE_PLAN_PATH = ART_DIR / "scene-plan.json"
ARCHIVE_DIR = ART_DIR / "archive"
SIZE = 320
SCALE = 4
CANVAS = SIZE * SCALE

NAVY = "#01183E"
BLUE = "#0559D5"
CYAN = "#18A0FB"
SLATE = "#5F718B"
PALE = "#D7E9FB"
MINT = "#4CC9A7"
AMBER = "#F0A43A"
RED = "#D94A59"
WHITE = "#FFFFFF"

SCENES = {
    "hardhat-visibility-review": {
        "subject": "A worker silhouette beneath a separate protective hardhat shape",
        "context": "A bounded industrial safety zone observed by a local camera",
        "signal": "A blue review halo marks the visual relationship between head and hardhat without declaring compliance",
        "composition": "Worker centered low with the hardhat and review halo clearly separated above",
    },
    "high-visibility-vest-review": {
        "subject": "A worker torso wearing a bright geometric safety vest",
        "context": "A warehouse aisle represented by two restrained vertical forms",
        "signal": "A blue outline marks a model-provided vest candidate for human review",
        "composition": "Torso fills the center with the vest as the dominant contrasting object",
    },
    "smoke-flame-visual-review": {
        "subject": "A security camera observing one compact smoke plume and flame form",
        "context": "An on-premises visual safety review scene",
        "signal": "An amber pulse connects the camera to the candidate plume without replacing life-safety sensors",
        "composition": "Camera anchors the lower left while plume and flame rise at upper right",
    },
    "plate-watchlist-review": {
        "subject": "A front-facing vehicle with a blank plate shape inside a shield ring",
        "context": "A locally authorized vehicle-list review lane",
        "signal": "A blue match pulse terminates at the shield while no plate characters are shown",
        "composition": "Vehicle spans the lower half with the shielded blank plate centered above its bumper",
    },
    "vehicle-attribute-log": {
        "subject": "A compact vehicle beside three model-classification color tokens",
        "context": "Local vehicle appearance candidate logging without identity inference",
        "signal": "Three bounded geometric tokens represent unverified model attributes",
        "composition": "Vehicle sits left of center with attribute tokens stacked on the right",
    },
    "parking-violation-dwell": {
        "subject": "A parked vehicle inside a clearly bounded zone beside a clock",
        "context": "A customer-configured restricted parking review area",
        "signal": "A blue perimeter and amber clock show sustained zone presence rather than a legal conclusion",
        "composition": "Vehicle fills the lower zone while the clock overlaps the upper right boundary",
    },
    "stopped-vehicle-lane": {
        "subject": "A vehicle resting between two lane lines with a compact clock",
        "context": "A traffic lane observed for low image-plane movement",
        "signal": "Short motion traces end before the vehicle to indicate sustained stillness",
        "composition": "Lane runs diagonally behind a centered vehicle with clock at upper right",
    },
    "traffic-queue-spillback": {
        "subject": "Three vehicles forming a compact queue beyond a bounded threshold line",
        "context": "A traffic approach monitored for sustained queue growth",
        "signal": "An amber boundary pulse marks queue spillback for operator review",
        "composition": "Vehicles recede diagonally from lower left to upper right across the threshold",
    },
    "unusual-dwell-baseline": {
        "subject": "An anonymous person silhouette beside a clock and a row of baseline dots",
        "context": "A local rolling dwell baseline with no identity recognition",
        "signal": "One elevated blue dot contrasts with the compact median group",
        "composition": "Person anchors left while clock and baseline dots balance the right side",
    },
    "queue-abandonment-review": {
        "subject": "A short queue of anonymous people with one figure following an exit path",
        "context": "A configured queue and service area represented without identity",
        "signal": "A blue route bends away before reaching the mint service marker",
        "composition": "Queue occupies the left half while the departing path opens toward the lower right",
    },
    "pedestrian-vehicle-conflict": {
        "subject": "An anonymous pedestrian and road vehicle separated by a measured gap",
        "context": "A shared movement area observed in image space",
        "signal": "An amber proximity arc marks a review candidate without declaring a near miss",
        "composition": "Pedestrian and vehicle face across the center with the arc between them",
    },
    "forklift-pedestrian-proximity": {
        "subject": "A compact forklift and anonymous pedestrian in a warehouse aisle",
        "context": "A domain-model industrial proximity review zone",
        "signal": "A red-orange distance arc highlights close image-plane tracks",
        "composition": "Forklift anchors lower left and pedestrian stands right with open space between",
    },
    "perimeter-climb-review": {
        "subject": "An anonymous pose silhouette beside a vertical fence boundary",
        "context": "A configured perimeter line observed with pose keypoints",
        "signal": "Raised arms and a blue boundary halo mark a sustained climbing-pose candidate",
        "composition": "Fence occupies the right third while the pose rises through the center",
    },
    "vehicle-wrong-way": {
        "subject": "A vehicle crossing a directional line opposite a large route arrow",
        "context": "A configured one-way vehicle crossing review",
        "signal": "Contrasting blue and amber directions show the observed crossing mismatch",
        "composition": "Vehicle moves diagonally across center while the allowed arrow runs behind it",
    },
    "occupancy-flow-anomaly": {
        "subject": "A small anonymous group beside a rolling sequence of count tokens",
        "context": "A local occupancy baseline with no biometric identification",
        "signal": "One elevated blue token differs from the slate median tokens",
        "composition": "People cluster left while the count sequence rises across the right",
    },
    "floor-water-change-review": {
        "subject": "A bounded floor zone with a reflective blue puddle-like shape and review lens",
        "context": "A local appearance-change metric rather than confirmed water detection",
        "signal": "Concentric ripples and a review halo mark a sustained visual change",
        "composition": "Floor plane fills the lower half while the lens hovers above the changed region",
    },
    "unusual-motion-baseline": {
        "subject": "An anonymous moving figure with two offset motion silhouettes",
        "context": "A locally learned frame-to-frame motion-energy baseline",
        "signal": "A rising blue waveform marks sustained motion energy above the median",
        "composition": "Figure occupies center left and waveform sweeps upward on the right",
    },
    "object-removal-review": {
        "subject": "A solid package beside its dashed empty-position outline on a pedestal",
        "context": "A configured asset zone with a local object-count baseline",
        "signal": "A blue review ring links the present object to the empty position",
        "composition": "Solid object anchors left and outlined absence balances the right",
    },
    "assembly-stage-order-review": {
        "subject": "Three distinct mechanical stage pieces connected by directional arcs",
        "context": "A station-specific model sequence requiring operator verification",
        "signal": "An amber exception arc skips the expected middle stage",
        "composition": "Three stage pieces progress left to right across the center",
    },
    "shipping-label-presence-review": {
        "subject": "A sealed package with one blank label panel and a review lens",
        "context": "A package and label association model with no readable text",
        "signal": "A blue halo marks the blank panel position inside the package boundary",
        "composition": "Package fills the center with label panel high right and lens overlapping its edge",
    },
}


def sc(value: float) -> int:
    return round(value * SCALE)


def _box(values):
    return tuple(sc(value) for value in values)


def rounded(draw, box, radius=8, *, fill=None, outline=None, width=1):
    draw.rounded_rectangle(
        _box(box), radius=sc(radius), fill=fill, outline=outline, width=sc(width)
    )


def ellipse(draw, box, *, fill=None, outline=None, width=1):
    draw.ellipse(_box(box), fill=fill, outline=outline, width=sc(width))


def line(draw, points, *, fill=NAVY, width=4):
    draw.line([(sc(x), sc(y)) for x, y in points], fill=fill, width=sc(width), joint="curve")


def polygon(draw, points, *, fill=None, outline=None, width=1):
    scaled = [(sc(x), sc(y)) for x, y in points]
    draw.polygon(scaled, fill=fill)
    if outline:
        draw.line(scaled + [scaled[0]], fill=outline, width=sc(width), joint="curve")


def person(draw, x, y, scale=1.0, color=NAVY, arms="down"):
    ellipse(draw, (x + 18 * scale, y, x + 42 * scale, y + 24 * scale), fill=color)
    rounded(draw, (x + 13 * scale, y + 27 * scale, x + 47 * scale, y + 78 * scale), 12 * scale, fill=color)
    if arms == "up":
        line(draw, [(x + 18 * scale, y + 39 * scale), (x + 2 * scale, y + 8 * scale)], fill=color, width=max(3, 8 * scale))
        line(draw, [(x + 42 * scale, y + 39 * scale), (x + 58 * scale, y + 8 * scale)], fill=color, width=max(3, 8 * scale))
    else:
        line(draw, [(x + 16 * scale, y + 40 * scale), (x + 2 * scale, y + 66 * scale)], fill=color, width=max(3, 8 * scale))
        line(draw, [(x + 44 * scale, y + 40 * scale), (x + 58 * scale, y + 66 * scale)], fill=color, width=max(3, 8 * scale))
    line(draw, [(x + 24 * scale, y + 76 * scale), (x + 17 * scale, y + 109 * scale)], fill=color, width=max(3, 9 * scale))
    line(draw, [(x + 36 * scale, y + 76 * scale), (x + 44 * scale, y + 109 * scale)], fill=color, width=max(3, 9 * scale))


def car(draw, x, y, scale=1.0, color=BLUE):
    polygon(draw, [(x + 14*scale,y + 34*scale),(x + 31*scale,y + 12*scale),(x + 82*scale,y + 12*scale),(x + 101*scale,y + 34*scale)], fill=PALE, outline=NAVY, width=3)
    rounded(draw, (x, y + 31*scale, x + 116*scale, y + 76*scale), 13*scale, fill=color, outline=NAVY, width=3)
    ellipse(draw, (x + 18*scale,y + 65*scale,x + 43*scale,y + 90*scale), fill=NAVY)
    ellipse(draw, (x + 77*scale,y + 65*scale,x + 102*scale,y + 90*scale), fill=NAVY)


def clock(draw, cx, cy, size=52):
    ellipse(draw, (cx-size/2,cy-size/2,cx+size/2,cy+size/2), fill=PALE, outline=NAVY, width=4)
    line(draw, [(cx,cy),(cx,cy-size*.27)], fill=AMBER, width=5)
    line(draw, [(cx,cy),(cx+size*.2,cy+size*.12)], fill=AMBER, width=5)


def package(draw, x, y, scale=1.0):
    polygon(draw, [(x,y+28*scale),(x+55*scale,y),(x+111*scale,y+28*scale),(x+111*scale,y+102*scale),(x+55*scale,y+130*scale),(x,y+102*scale)], fill=BLUE, outline=NAVY, width=4)
    line(draw, [(x,y+28*scale),(x+55*scale,y+56*scale),(x+111*scale,y+28*scale)], fill=PALE, width=4)
    line(draw, [(x+55*scale,y+56*scale),(x+55*scale,y+130*scale)], fill=PALE, width=4)


def arrow(draw, points, color=BLUE, width=9):
    line(draw, points, fill=color, width=width)
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    angle = math.atan2(y2-y1, x2-x1)
    length = 18
    polygon(draw, [(x2,y2),(x2-length*math.cos(angle-.55),y2-length*math.sin(angle-.55)),(x2-length*math.cos(angle+.55),y2-length*math.sin(angle+.55))], fill=color)


def draw_art(row: dict) -> Image.Image:
    module_id = row["id"]
    if module_id not in SCENES:
        raise ValueError(f"unsupported vendor plugin art id: {module_id}")
    digest = hashlib.sha256(module_id.encode("utf-8")).digest()
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ellipse(draw, (50, 52, 270, 270), fill=(215, 233, 251, 132))

    if module_id == "hardhat-visibility-review":
        person(draw, 126, 112, .92)
        polygon(draw, [(129,111),(141,91),(178,91),(191,111)], fill=AMBER, outline=NAVY, width=3)
        rounded(draw, (124,107,196,118), 5, fill=AMBER, outline=NAVY, width=3)
        ellipse(draw, (116,78,204,130), outline=BLUE, width=5)
    elif module_id == "high-visibility-vest-review":
        person(draw, 126, 88, 1.0)
        polygon(draw, [(139,119),(154,111),(166,111),(181,119),(176,170),(144,170)], fill=AMBER, outline=WHITE, width=3)
        line(draw, [(160,115),(160,168)], fill=WHITE, width=4)
    elif module_id == "smoke-flame-visual-review":
        rounded(draw, (56,165,145,219), 14, fill=NAVY)
        ellipse(draw, (81,174,132,225), fill=PALE)
        ellipse(draw, (92,185,121,214), fill=BLUE)
        polygon(draw, [(193,225),(175,190),(196,153),(202,181),(222,140),(238,185),(226,225)], fill=AMBER, outline=NAVY, width=3)
        for box in ((180,92,222,135),(204,66,252,111),(157,119,205,160)):
            ellipse(draw, box, fill=SLATE)
    elif module_id == "plate-watchlist-review":
        car(draw, 102, 133, 1.0)
        rounded(draw, (133,174,187,197), 5, fill=WHITE, outline=NAVY, width=3)
        ellipse(draw, (119,154,202,215), outline=MINT, width=6)
    elif module_id == "vehicle-attribute-log":
        car(draw, 62, 139, .92)
        for index, color in enumerate((BLUE, MINT, AMBER)):
            ellipse(draw, (214,102+index*47,247,135+index*47), fill=color, outline=NAVY, width=3)
    elif module_id == "parking-violation-dwell":
        rounded(draw, (56,118,251,240), 18, outline=BLUE, width=6)
        car(draw, 77, 151, 1.0)
        clock(draw, 231, 104, 61)
    elif module_id == "stopped-vehicle-lane":
        line(draw, [(62,74),(112,262)], fill=SLATE, width=6)
        line(draw, [(208,58),(257,247)], fill=SLATE, width=6)
        car(draw, 99, 140, .95)
        for x in (66,82,98):
            line(draw, [(x,168),(x+13,168)], fill=CYAN, width=4)
        clock(draw, 230, 95, 52)
    elif module_id == "traffic-queue-spillback":
        for index in range(3):
            car(draw, 51+index*62, 184-index*47, .56)
        line(draw, [(59,224),(258,71)], fill=AMBER, width=5)
        ellipse(draw, (48,213,70,235), fill=RED)
    elif module_id == "unusual-dwell-baseline":
        person(draw, 71, 117, .9)
        clock(draw, 210, 134, 67)
        for index in range(4):
            ellipse(draw, (153+index*24,222,167+index*24,236), fill=SLATE)
        ellipse(draw, (225,188,243,206), fill=BLUE)
    elif module_id == "queue-abandonment-review":
        for index in range(3):
            person(draw, 48+index*44, 128, .55, SLATE)
        person(draw, 201, 131, .58, NAVY)
        arrow(draw, [(173,219),(198,235),(252,232)], CYAN, 7)
        ellipse(draw, (146,73,175,102), fill=MINT, outline=NAVY, width=3)
    elif module_id == "pedestrian-vehicle-conflict":
        person(draw, 57, 135, .75)
        car(draw, 155, 155, .82)
        line(draw, [(121,177),(151,177)], fill=AMBER, width=7)
        ellipse(draw, (129,166,143,180), fill=RED)
    elif module_id == "forklift-pedestrian-proximity":
        rounded(draw, (52,159,139,222), 8, fill=AMBER, outline=NAVY, width=4)
        line(draw, [(136,162),(136,236),(169,236)], fill=NAVY, width=8)
        ellipse(draw, (65,210,94,239), fill=NAVY)
        ellipse(draw, (111,210,140,239), fill=NAVY)
        person(draw, 207, 132, .7)
        line(draw, [(174,181),(205,181)], fill=RED, width=6)
    elif module_id == "perimeter-climb-review":
        for x in (185,215,245):
            line(draw, [(x,70),(x,252)], fill=SLATE, width=5)
        for y in (97,132,167,202,237):
            line(draw, [(177,y),(255,y)], fill=SLATE, width=3)
        person(draw, 104, 99, 1.0, NAVY, "up")
        ellipse(draw, (91,82,191,233), outline=BLUE, width=5)
    elif module_id == "vehicle-wrong-way":
        arrow(draw, [(60,238),(251,82)], BLUE, 10)
        car(draw, 108, 137, .86, AMBER)
        arrow(draw, [(222,213),(117,126)], RED, 7)
    elif module_id == "occupancy-flow-anomaly":
        for index in range(3):
            person(draw, 50+index*50, 147-index*8, .58, NAVY if index==0 else SLATE)
        for index, height in enumerate((18,20,19,62)):
            rounded(draw, (205+index*18,229-height,217+index*18,229), 4, fill=BLUE if index==3 else SLATE)
    elif module_id == "floor-water-change-review":
        polygon(draw, [(48,200),(150,115),(272,190),(170,270)], fill=PALE, outline=NAVY, width=4)
        ellipse(draw, (110,170,225,230), fill=(24,160,251,185), outline=BLUE, width=4)
        ellipse(draw, (132,184,204,217), outline=WHITE, width=3)
        ellipse(draw, (188,75,259,146), outline=NAVY, width=7)
        line(draw, [(239,130),(270,162)], fill=NAVY, width=8)
    elif module_id == "unusual-motion-baseline":
        person(draw, 80, 126, .8, SLATE)
        person(draw, 109, 111, .8, NAVY)
        line(draw, [(178,208),(194,208),(204,171),(219,239),(233,191),(247,208),(267,208)], fill=BLUE, width=6)
    elif module_id == "object-removal-review":
        package(draw, 55, 126, .74)
        rounded(draw, (183,128,260,221), 6, outline=SLATE, width=4)
        for y in (128,221):
            for x in range(188,256,18):
                line(draw, [(x,y),(x+8,y)], fill=SLATE, width=3)
        ellipse(draw, (45,112,272,241), outline=BLUE, width=4)
    elif module_id == "assembly-stage-order-review":
        for index, color in enumerate((BLUE, SLATE, MINT)):
            ellipse(draw, (49+index*91,133,105+index*91,189), fill=color, outline=NAVY, width=4)
            ellipse(draw, (67+index*91,151,87+index*91,171), fill=PALE)
        arrow(draw, [(105,161),(138,161)], BLUE, 6)
        arrow(draw, [(196,161),(229,161)], AMBER, 6)
        arrow(draw, [(101,216),(238,216)], RED, 5)
    elif module_id == "shipping-label-presence-review":
        package(draw, 89, 95, 1.18)
        rounded(draw, (153,131,210,173), 5, fill=WHITE, outline=NAVY, width=3)
        ellipse(draw, (137,114,226,190), outline=BLUE, width=6)

    # A tiny deterministic constellation makes every illustration pixel-unique
    # without adding glyphs, typography, or decorative tiles.
    angle = (digest[0] / 255.0) * math.tau
    for index in range(3):
        theta = angle + index * math.tau / 3
        radius = 124 + digest[index + 1] % 8
        x = 160 + math.cos(theta) * radius
        y = 160 + math.sin(theta) * radius
        ellipse(draw, (x-4,y-4,x+4,y+4), fill=(BLUE, CYAN, MINT)[index])

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
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


def _save_webp(path: Path, image: Image.Image) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".webp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, "WEBP", lossless=True, method=6, exact=True)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_module_art_script():
    path = ROOT / "scripts" / "generate_module_art.py"
    spec = importlib.util.spec_from_file_location("active_module_art", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    catalog_rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    catalog = {row["id"]: row for row in catalog_rows}
    active_ids = set(catalog)
    vendor_ids = set(selection["vendor_inspired_ids"])
    if len(catalog_rows) != 100 or len(catalog) != 100:
        raise SystemExit("expected exact 100-entry active catalog")
    if vendor_ids != set(SCENES) or len(vendor_ids) != 20:
        raise SystemExit("vendor art scenes must exactly match the selected 20 plugins")
    if not vendor_ids.issubset(active_ids):
        raise SystemExit("selected vendor plugins are missing from active catalog")

    original_plan = json.loads(SCENE_PLAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(original_plan, dict):
        raise SystemExit("scene plan must be an object")
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archived_plan_path = ARCHIVE_DIR / "scene-plan-251.json"
    if len(original_plan) > 100 and not archived_plan_path.exists():
        _atomic_text(
            archived_plan_path,
            json.dumps(original_plan, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        )

    active_plan = {
        module_id: original_plan[module_id]
        for module_id in active_ids - vendor_ids
        if module_id in original_plan
    }
    active_plan.update(SCENES)
    if set(active_plan) != active_ids:
        missing = sorted(active_ids - set(active_plan))
        raise SystemExit(f"active scene plan missing selected entries: {missing}")

    webp_archive = ARCHIVE_DIR / "webp"
    webp_archive.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(ART_DIR.glob("*.webp")):
        if path.stem in active_ids:
            continue
        target = webp_archive / path.name
        if target.exists():
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise SystemExit(f"archive collision for {path.name}")
            path.unlink()
        else:
            os.replace(path, target)
        moved += 1

    for module_id in sorted(vendor_ids):
        _save_webp(ART_DIR / f"{module_id}.webp", draw_art(catalog[module_id]))

    top_level_ids = {path.stem for path in ART_DIR.glob("*.webp")}
    if top_level_ids != active_ids:
        raise SystemExit(
            f"active art mismatch: extras={sorted(top_level_ids-active_ids)} "
            f"missing={sorted(active_ids-top_level_ids)}"
        )
    _atomic_text(
        SCENE_PLAN_PATH,
        json.dumps(
            {module_id: active_plan[module_id] for module_id in sorted(active_plan)},
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
    )

    module_art = _load_module_art_script()
    registry = module_art.prompt_registry(catalog, active_plan)
    module_art.write_manifest(sorted(active_ids), registry)
    print(
        f"Reconciled {len(active_ids)} active WebPs; generated {len(vendor_ids)} "
        f"vendor-plugin images; archived {moved} retired WebPs"
    )


if __name__ == "__main__":
    main()
