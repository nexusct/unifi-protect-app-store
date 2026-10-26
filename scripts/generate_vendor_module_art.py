#!/usr/bin/env python3
"""Generate and reconcile artwork for the 30 audited marketplace super skills.

Retired top-level WebPs are moved into ``assets/module-art/archive/webp`` rather
rather than deleted. Existing selected artwork is preserved byte-for-byte. This script
creates only the 30 super-skill illustrations, rewrites the active 105-entry scene
plan, and refreshes the art manifest/prompt registry.
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

SUPER_SCENE_ROWS = {
    "secured-exit-approach-review": (
        "An anonymous resident silhouette moving through an approach area toward a secured exit line",
        "A configured care-facility exit route observed locally without identity recognition",
        "Three blue route nodes show the sustained approach sequence before a review boundary",
        "Person and route occupy the center with a restrained door boundary on the right",
    ),
    "room-exit-sequence-review": (
        "A privacy-preserving skeleton moving from a room zone through a doorway into a hall",
        "A configured resident-room path rendered only as pose geometry",
        "Three connected keypoint poses show room-to-door-to-hall progression",
        "Sparse skeleton sequence moves left to right across three open zones",
    ),
    "mobility-aid-egress-obstruction": (
        "A mobility-aid route intersected by one stationary geometric obstacle",
        "A bounded care-facility circulation path with no person identity",
        "An amber dwell clock and red overlap arc mark the persistent obstruction candidate",
        "Clear route arrow runs behind the obstacle with the clock at upper right",
    ),
    "controlled-room-two-person-review": (
        "An access badge pulse at a controlled doorway beside two anonymous occupants",
        "A room-entry review combining normalized Access events with local person counts",
        "A blue credential pulse connects the door to the occupancy count change",
        "Door anchors left while the anonymous room group balances the right",
    ),
    "care-area-occupancy-imbalance": (
        "Two anonymous occupancy groups separated by a directional threshold line",
        "A configured care-unit boundary measured with local person counts",
        "Opposing blue arrows show entries and exits resolving to a net delta",
        "Small groups flank the center line with count tokens below",
    ),
    "waiting-room-flow-ledger": (
        "A compact anonymous waiting group progressing toward one service point",
        "A configured waiting-room path from arrival through service and exit",
        "A four-node blue route shows arrivals, waiting, service, and departures",
        "Waiting group fills the left while the service marker and exit open to the right",
    ),
    "vision-estate-health": (
        "Three camera silhouettes beside one consolidated health shield",
        "A multi-camera estate reviewed for image and connection health",
        "Blue, amber, and slate status pulses converge into one digest shield",
        "Camera row spans the lower half with the shield centered above",
    ),
    "perimeter-event-verifier": (
        "An anonymous person inside a bounded perimeter beside a patrol shield",
        "A configured perimeter zone correlated with recent patrol evidence",
        "An amber dwell ring and blue verification pulse identify the review sequence",
        "Boundary fills the center with person low and patrol shield high right",
    ),
    "multi-zone-intrusion-progression": (
        "An anonymous track moving through three nested security zones",
        "A local perimeter progression from outer approach to protected interior",
        "Three increasingly strong route pulses mark ordered zone penetration",
        "Concentric open zones recede toward the upper right along one track",
    ),
    "package-room-chain-review": (
        "A sealed package moving between receipt, secure hold, and release zones",
        "A local package workflow correlated with normalized door-access events",
        "Three blue custody nodes and one credential pulse form a bounded timeline",
        "Package appears at center with receipt and release markers on either side",
    ),
    "after-hours-multi-camera-corroboration": (
        "Two camera silhouettes observing the same anonymous after-hours event",
        "A configured site where independent camera observations corroborate activity",
        "Matching blue pulses from both cameras converge on one review marker",
        "Cameras anchor opposite corners with a person silhouette between them",
    ),
    "door-alarm-observed-response-timer": (
        "A forced-door alert, responder silhouette, and closed-door state on one timeline",
        "A normalized Access alarm correlated with local visual response",
        "Amber-to-blue timeline nodes show alarm, arrival, and restoration",
        "Horizontal timeline spans the center with door on the right",
    ),
    "anonymous-zone-funnel": (
        "Anonymous visitors progressing through approach, entry, engage, and convert zones",
        "A configured retail journey measured with local track transitions",
        "Four narrowing blue funnel stages show bounded progression rates",
        "Wide approach group at left narrows toward one mint completion marker",
    ),
    "queue-service-rate-digest": (
        "A customer queue facing one active service position and one empty position",
        "A configured service area comparing sustained demand with visible capacity",
        "An amber gap arc links the long queue to the unstaffed service marker",
        "Queue occupies the left with paired service positions on the right",
    ),
    "curbside-handoff-timer": (
        "A vehicle arrival, anonymous handoff figure, and departure path",
        "A configured curbside workflow observed without plate or face identity",
        "Three blue nodes mark arrival, handoff, and completed departure",
        "Vehicle anchors lower left while the route bends through center to upper right",
    ),
    "drive-thru-lane-balance": (
        "Two parallel vehicle queues with visibly different sustained lengths",
        "A paired drive-thru approach compared with anonymous vehicle counts",
        "An amber balance bar highlights the persistent lane difference",
        "Two lanes run upward in parallel with the shorter queue on the right",
    ),
    "table-reset-delay-review": (
        "An empty dining table beside a reset clock and service-approach marker",
        "A configured table zone reviewed after guests depart",
        "A blue readiness halo appears after the sustained empty interval",
        "Table fills the center with clock upper right and approach arrow below",
    ),
    "high-traffic-service-trigger": (
        "Vehicles crossing a directional threshold beside a quality-review trigger",
        "A configured traffic line that opens review only after enough observations",
        "Blue crossing pulses accumulate into one amber trigger marker",
        "Directional line cuts the center with vehicles distributed along the route",
    ),
    "dock-stage-turnaround": (
        "A truck moving through arrival, staging, dock, and departure zones",
        "A configured dock-door cycle measured as one bounded operational timeline",
        "Four blue nodes and a compact clock show stage durations",
        "Truck anchors center while timeline nodes arc from lower left to upper right",
    ),
    "dock-apron-conflict-review": (
        "An anonymous pedestrian and vehicle on converging image-plane paths",
        "A configured shared movement zone using track velocity and proximity",
        "An amber predicted-gap arc marks a sustained review candidate",
        "Pedestrian and vehicle face across open center space with paths converging",
    ),
    "forklift-route-deviation-review": (
        "A compact forklift leaving a configured warehouse travel corridor",
        "A domain-model industrial route review with no automated machine control",
        "A red deviation arc breaks away from the blue permitted path",
        "Permitted route runs diagonally while forklift turns toward the lower edge",
    ),
    "aisle-blockage-duration-review": (
        "A warehouse aisle occupied by one stationary pallet-like object",
        "A configured circulation aisle monitored for sustained obstruction",
        "An amber dwell clock and red blocked-path segment mark persistence",
        "Aisle lines recede behind the centered obstacle with clock upper right",
    ),
    "cycle-step-timer": (
        "Three machine-stage shapes connected in an expected production sequence",
        "A domain-model workcell review requiring operator verification",
        "An amber exception arc shows a missing or reordered stage",
        "Three stage pieces progress left to right with exception arc below",
    ),
    "yard-queue-bottleneck-digest": (
        "A compact vehicle queue between yard arrival and release boundaries",
        "A configured logistics yard measured for sustained congestion",
        "An amber bottleneck ring surrounds the densest queue segment",
        "Vehicles recede toward the upper right between two boundary lines",
    ),
    "multi-class-flow-ledger": (
        "Anonymous people and vehicles crossing one directional line",
        "A configured boundary producing separate class and direction counts",
        "Opposing blue arrows and distinct count tokens separate the flow classes",
        "Crossing line fills the center with people left and vehicles right",
    ),
    "anonymous-space-utilization-percentiles": (
        "Anonymous occupancy groups beside a compact percentile distribution",
        "A configured space sampled locally over a bounded reporting interval",
        "Three slate bars and one blue percentile marker summarize utilization",
        "People cluster left while the ordered percentile bars rise on the right",
    ),
    "route-completion-ledger": (
        "An anonymous tracked route from start through checkpoint and dropoff to exit",
        "A configured operational journey measured without identity persistence",
        "Four blue nodes show completion while an amber branch marks a skipped checkpoint",
        "Route sweeps across the center with dropoff package at the third node",
    ),
    "zone-activity-schedule-baseline": (
        "An anonymous activity count beside a clock divided into schedule windows",
        "A local baseline comparing activity only with matching time slots",
        "One blue count rises above a compact slate baseline group",
        "Clock anchors left while baseline dots and exception marker fill the right",
    ),
    "shift-change-flow-review": (
        "Anonymous people crossing a boundary during one highlighted shift window",
        "A configured shift schedule summarized with local directional counts",
        "A blue flow arrow narrows at an amber bottleneck marker",
        "Clock sits upper left while crossing silhouettes span the center",
    ),
    "exception-evidence-casebook": (
        "A shielded evidence folder containing blank redacted image panels",
        "A bounded local casebook assembled from correlated alerts and access events",
        "Blue chain links and solid redaction bars show integrity without readable content",
        "Folder fills the center with shield above and chain-link markers below",
    ),
}

_SCENE_FIELDS = ("subject", "context", "signal", "composition")
SCENES = {
    module_id: dict(zip(_SCENE_FIELDS, values, strict=True))
    for module_id, values in SUPER_SCENE_ROWS.items()
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


def camera_shape(draw, x, y, scale=1.0):
    rounded(draw, (x, y, x + 72*scale, y + 45*scale), max(1, round(9*scale)), fill=NAVY)
    ellipse(draw, (x + 19*scale, y + 7*scale, x + 58*scale, y + 39*scale), fill=PALE, outline=BLUE, width=max(2, round(3*scale)))
    polygon(draw, [(x + 72*scale, y + 12*scale), (x + 94*scale, y + 4*scale), (x + 94*scale, y + 42*scale), (x + 72*scale, y + 34*scale)], fill=BLUE)


def door_shape(draw, x, y, width=62, height=148):
    rounded(draw, (x, y, x + width, y + height), 4, outline=NAVY, width=6)
    line(draw, [(x + 9, y + height - 8), (x + 9, y + 12), (x + width - 9, y + 12)], fill=BLUE, width=5)
    ellipse(draw, (x + width - 19, y + height*.52, x + width - 10, y + height*.52 + 9), fill=AMBER)


def skeleton(draw, x, y, scale=1.0, color=NAVY):
    ellipse(draw, (x + 19*scale, y, x + 39*scale, y + 20*scale), outline=color, width=max(2, round(4*scale)))
    line(draw, [(x + 29*scale, y + 20*scale), (x + 29*scale, y + 69*scale)], fill=color, width=max(2, round(5*scale)))
    line(draw, [(x + 29*scale, y + 31*scale), (x + 5*scale, y + 51*scale)], fill=color, width=max(2, round(4*scale)))
    line(draw, [(x + 29*scale, y + 31*scale), (x + 54*scale, y + 48*scale)], fill=color, width=max(2, round(4*scale)))
    line(draw, [(x + 29*scale, y + 69*scale), (x + 11*scale, y + 103*scale)], fill=color, width=max(2, round(5*scale)))
    line(draw, [(x + 29*scale, y + 69*scale), (x + 48*scale, y + 103*scale)], fill=color, width=max(2, round(5*scale)))


def forklift_shape(draw, x, y, scale=1.0):
    rounded(draw, (x, y + 33*scale, x + 78*scale, y + 91*scale), max(1, round(7*scale)), fill=AMBER, outline=NAVY, width=4)
    rounded(draw, (x + 42*scale, y, x + 75*scale, y + 45*scale), max(1, round(5*scale)), fill=PALE, outline=NAVY, width=4)
    line(draw, [(x + 77*scale, y + 5*scale), (x + 77*scale, y + 105*scale), (x + 116*scale, y + 105*scale)], fill=NAVY, width=max(4, round(8*scale)))
    ellipse(draw, (x + 8*scale, y + 78*scale, x + 36*scale, y + 106*scale), fill=NAVY)
    ellipse(draw, (x + 52*scale, y + 78*scale, x + 80*scale, y + 106*scale), fill=NAVY)


def _draw_super_scene(draw, module_id: str) -> None:
    if module_id == "secured-exit-approach-review":
        person(draw, 55, 132, .7)
        door_shape(draw, 210, 76)
        for x, y in ((110, 223), (145, 198), (181, 170)):
            ellipse(draw, (x-7, y-7, x+7, y+7), fill=BLUE)
        arrow(draw, [(88, 228), (145, 198), (214, 159)], AMBER, 6)
    elif module_id == "room-exit-sequence-review":
        skeleton(draw, 45, 142, .52, SLATE)
        skeleton(draw, 116, 117, .62, BLUE)
        skeleton(draw, 205, 91, .72, NAVY)
        line(draw, [(103, 239), (191, 205)], fill=CYAN, width=5)
    elif module_id == "mobility-aid-egress-obstruction":
        ellipse(draw, (51, 145, 151, 245), outline=NAVY, width=9)
        ellipse(draw, (84, 91, 120, 127), fill=NAVY)
        line(draw, [(102, 128), (125, 169), (174, 169)], fill=NAVY, width=9)
        line(draw, [(125, 169), (99, 205)], fill=NAVY, width=8)
        rounded(draw, (211, 157, 265, 229), 8, fill=AMBER, outline=NAVY, width=5)
        arrow(draw, [(148, 235), (184, 217), (203, 196)], BLUE, 7)
    elif module_id == "controlled-room-two-person-review":
        door_shape(draw, 42, 83, 55, 151)
        person(draw, 135, 127, .62)
        person(draw, 202, 127, .62, SLATE)
        ellipse(draw, (89, 68, 130, 109), fill=PALE, outline=BLUE, width=4)
        line(draw, [(101, 88), (110, 97), (122, 78)], fill=MINT, width=4)
    elif module_id == "care-area-occupancy-imbalance":
        for index in range(3):
            person(draw, 44 + index*42, 146, .48, NAVY)
        person(draw, 222, 157, .48, SLATE)
        line(draw, [(160, 100), (160, 234)], fill=BLUE, width=5)
        arrow(draw, [(186, 125), (218, 125)], AMBER, 6)
    elif module_id == "waiting-room-flow-ledger":
        for index in range(3):
            person(draw, 39 + index*43, 149, .48, SLATE)
        rounded(draw, (194, 128, 265, 198), 7, fill=PALE, outline=NAVY, width=4)
        ellipse(draw, (218, 92, 242, 116), fill=MINT, outline=NAVY, width=3)
        arrow(draw, [(145, 224), (190, 211), (228, 180)], BLUE, 6)
    elif module_id == "vision-estate-health":
        camera_shape(draw, 37, 151, .62)
        camera_shape(draw, 123, 139, .68)
        camera_shape(draw, 214, 151, .62)
        ellipse(draw, (125, 67, 195, 137), fill=PALE, outline=BLUE, width=5)
        line(draw, [(142, 103), (154, 116), (180, 86)], fill=MINT, width=6)
    elif module_id == "perimeter-event-verifier":
        camera_shape(draw, 46, 91, .9)
        line(draw, [(178, 74), (178, 250)], fill=SLATE, width=8)
        line(draw, [(221, 74), (221, 250)], fill=SLATE, width=8)
        for y in (105, 153, 201):
            line(draw, [(172, y), (227, y)], fill=SLATE, width=4)
        polygon(draw, [(260, 139), (287, 149), (282, 189), (260, 211), (238, 189), (233, 149)], fill=PALE, outline=BLUE, width=5)
        line(draw, [(244, 174), (256, 186), (275, 158)], fill=MINT, width=6)
    elif module_id == "multi-zone-intrusion-progression":
        ellipse(draw, (55, 65, 267, 257), outline=SLATE, width=5)
        ellipse(draw, (97, 99, 245, 237), outline=BLUE, width=6)
        ellipse(draw, (138, 132, 224, 216), outline=AMBER, width=6)
        person(draw, 145, 121, .54)
        arrow(draw, [(55, 237), (105, 207), (145, 178)], MINT, 7)
    elif module_id == "package-room-chain-review":
        package(draw, 111, 108, .9)
        for index, x in enumerate((53, 160, 268)):
            ellipse(draw, (x-10, 235, x+10, 255), fill=(BLUE, MINT, AMBER)[index])
        line(draw, [(63, 245), (150, 245), (170, 245), (258, 245)], fill=NAVY, width=5)
        rounded(draw, (53, 84, 91, 125), 6, fill=PALE, outline=BLUE, width=4)
    elif module_id == "after-hours-multi-camera-corroboration":
        camera_shape(draw, 46, 94, .7)
        camera_shape(draw, 208, 94, .7)
        person(draw, 127, 157, .65)
        ellipse(draw, (139, 56, 181, 98), fill=AMBER)
        ellipse(draw, (151, 48, 185, 84), fill=(215, 233, 251, 255))
        line(draw, [(104, 129), (146, 172), (216, 129)], fill=CYAN, width=5)
    elif module_id == "door-alarm-observed-response-timer":
        door_shape(draw, 214, 80)
        person(draw, 128, 132, .58)
        line(draw, [(48, 237), (248, 237)], fill=NAVY, width=5)
        for x, color in ((68, RED), (151, BLUE), (237, MINT)):
            ellipse(draw, (x-9, 228, x+9, 246), fill=color)
        clock(draw, 75, 116, 55)
    elif module_id == "anonymous-zone-funnel":
        for index in range(4):
            x = 42 + index*64
            size = .52 - index*.07
            person(draw, x, 150 + index*9, size, NAVY if index == 3 else SLATE)
        polygon(draw, [(39, 91), (276, 91), (230, 231), (89, 231)], outline=BLUE, width=5)
        arrow(draw, [(76, 116), (158, 116), (242, 116)], MINT, 6)
    elif module_id == "queue-service-rate-digest":
        person(draw, 43, 147, .6, SLATE)
        person(draw, 103, 135, .65, NAVY)
        rounded(draw, (207, 151, 274, 221), 8, fill=BLUE, outline=NAVY, width=5)
        person(draw, 210, 104, .44, NAVY)
        arrow(draw, [(151, 225), (190, 203), (220, 184)], MINT, 7)
    elif module_id == "curbside-handoff-timer":
        car(draw, 45, 158, .72)
        person(draw, 179, 133, .58)
        rounded(draw, (225, 174, 263, 213), 5, fill=AMBER, outline=NAVY, width=3)
        clock(draw, 230, 102, 50)
        arrow(draw, [(77, 239), (159, 230), (257, 229)], CYAN, 6)
    elif module_id == "drive-thru-lane-balance":
        line(draw, [(69, 65), (69, 257)], fill=SLATE, width=5)
        line(draw, [(160, 65), (160, 257)], fill=SLATE, width=5)
        line(draw, [(251, 65), (251, 257)], fill=SLATE, width=5)
        for y in (98, 158, 218):
            car(draw, 78, y, .42, BLUE)
        car(draw, 169, 158, .42, AMBER)
        line(draw, [(92, 79), (226, 79)], fill=MINT, width=6)
    elif module_id == "table-reset-delay-review":
        rounded(draw, (73, 130, 217, 209), 12, fill=BLUE, outline=NAVY, width=6)
        for box in ((87,87,133,119),(157,87,203,119),(87,220,133,252),(157,220,203,252)):
            rounded(draw, box, 8, fill=AMBER, outline=NAVY, width=3)
        clock(draw, 255, 150, 62)
        ellipse(draw, (132, 153, 158, 179), fill=MINT, outline=NAVY, width=3)
    elif module_id == "high-traffic-service-trigger":
        line(draw, [(160, 66), (160, 255)], fill=AMBER, width=7)
        for index, y in enumerate((88, 144, 201)):
            car(draw, 55 if index % 2 == 0 else 170, y, .42, BLUE)
        for y in (91, 151, 211):
            ellipse(draw, (145, y, 159, y+14), fill=CYAN)
        ellipse(draw, (224, 66, 269, 111), outline=RED, width=5)
    elif module_id == "dock-stage-turnaround":
        car(draw, 99, 129, 1.0, BLUE)
        for index, x in enumerate((51, 116, 181, 246)):
            ellipse(draw, (x-9, 239, x+9, 257), fill=(SLATE, BLUE, MINT, AMBER)[index])
        line(draw, [(60, 248), (237, 248)], fill=NAVY, width=5)
        clock(draw, 239, 92, 54)
    elif module_id == "dock-apron-conflict-review":
        person(draw, 53, 133, .7)
        car(draw, 164, 156, .75, AMBER)
        arrow(draw, [(94, 225), (151, 184)], BLUE, 6)
        arrow(draw, [(248, 226), (176, 184)], RED, 6)
        polygon(draw, [(165,148),(172,166),(192,157),(181,177),(198,190),(176,188),(175,211),(162,192),(145,205),(152,183),(131,175),(154,169)], fill=RED)
    elif module_id == "forklift-route-deviation-review":
        forklift_shape(draw, 48, 126, 1.15)
        line(draw, [(50, 252), (126, 213), (226, 83)], fill=BLUE, width=8)
        arrow(draw, [(151, 199), (221, 220), (275, 248)], RED, 8)
    elif module_id == "aisle-blockage-duration-review":
        rounded(draw, (44, 93, 91, 239), 5, outline=SLATE, width=6)
        rounded(draw, (229, 93, 276, 239), 5, outline=SLATE, width=6)
        for y in (137, 183):
            line(draw, [(48, y), (87, y)], fill=SLATE, width=5)
            line(draw, [(233, y), (272, y)], fill=SLATE, width=5)
        rounded(draw, (116, 137, 208, 229), 9, fill=AMBER, outline=NAVY, width=5)
        line(draw, [(134, 155), (190, 211)], fill=RED, width=8)
        line(draw, [(190, 155), (134, 211)], fill=RED, width=8)
        clock(draw, 243, 101, 64)
    elif module_id == "cycle-step-timer":
        for index, color in enumerate((BLUE, SLATE, MINT)):
            rounded(draw, (42 + index*91, 128, 103 + index*91, 191), 9, fill=color, outline=NAVY, width=5)
        arrow(draw, [(104, 159), (129, 159)], BLUE, 6)
        arrow(draw, [(195, 159), (220, 159)], AMBER, 6)
        clock(draw, 160, 235, 58)
    elif module_id == "yard-queue-bottleneck-digest":
        line(draw, [(42, 73), (132, 158), (132, 257)], fill=SLATE, width=6)
        line(draw, [(278, 73), (188, 158), (188, 257)], fill=SLATE, width=6)
        car(draw, 45, 116, .5, BLUE)
        car(draw, 207, 116, .5, BLUE)
        car(draw, 126, 187, .58, AMBER)
        arrow(draw, [(86, 99), (142, 159)], CYAN, 6)
        arrow(draw, [(234, 99), (178, 159)], CYAN, 6)
        line(draw, [(137, 241), (183, 241)], fill=RED, width=9)
    elif module_id == "multi-class-flow-ledger":
        person(draw, 50, 135, .58)
        car(draw, 177, 156, .7, BLUE)
        line(draw, [(159, 63), (159, 256)], fill=AMBER, width=6)
        arrow(draw, [(78, 227), (138, 185)], CYAN, 5)
        arrow(draw, [(245, 226), (181, 185)], MINT, 5)
    elif module_id == "anonymous-space-utilization-percentiles":
        person(draw, 48, 134, .7, NAVY)
        for index, height in enumerate((52, 91, 130)):
            rounded(draw, (161 + index*36, 245-height, 187 + index*36, 245), 6, fill=(SLATE, BLUE, MINT)[index])
        line(draw, [(149, 246), (279, 246)], fill=NAVY, width=5)
    elif module_id == "route-completion-ledger":
        arrow(draw, [(46, 236), (93, 203), (151, 216), (207, 147), (269, 103)], BLUE, 7)
        for x, y, color in ((48,236,SLATE),(95,203,BLUE),(153,216,AMBER),(209,147,MINT),(269,103,NAVY)):
            ellipse(draw, (x-8,y-8,x+8,y+8), fill=color)
        package(draw, 178, 168, .38)
    elif module_id == "zone-activity-schedule-baseline":
        clock(draw, 91, 149, 90)
        for index, height in enumerate((24, 27, 23, 78)):
            rounded(draw, (166 + index*25, 227-height, 182 + index*25, 227), 4, fill=BLUE if index == 3 else SLATE)
        line(draw, [(157, 228), (270, 228)], fill=NAVY, width=4)
        ellipse(draw, (235, 93, 261, 119), fill=AMBER)
    elif module_id == "shift-change-flow-review":
        clock(draw, 78, 99, 57)
        line(draw, [(160, 72), (160, 254)], fill=AMBER, width=6)
        person(draw, 74, 151, .55, NAVY)
        person(draw, 210, 151, .55, SLATE)
        arrow(draw, [(119, 218), (153, 189)], BLUE, 5)
        arrow(draw, [(204, 219), (169, 189)], MINT, 5)
    elif module_id == "exception-evidence-casebook":
        rounded(draw, (68, 97, 244, 241), 12, fill=PALE, outline=NAVY, width=5)
        polygon(draw, [(69,97),(115,97),(127,78),(183,78),(195,97),(244,97)], fill=BLUE, outline=NAVY, width=4)
        polygon(draw, [(215,94),(270,115),(261,190),(215,224),(169,190),(160,115)], fill=PALE, outline=MINT, width=6)
        line(draw, [(181,158),(207,183),(251,126)], fill=MINT, width=9)
    else:
        raise ValueError(f"missing drawing recipe for {module_id}")


def draw_art(row: dict) -> Image.Image:
    module_id = row["id"]
    if module_id not in SCENES:
        raise ValueError(f"unsupported super-skill art id: {module_id}")
    digest = hashlib.sha256(module_id.encode("utf-8")).digest()
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ellipse(draw, (50, 52, 270, 270), fill=(215, 233, 251, 132))
    _draw_super_scene(draw, module_id)

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
    generated_ids = set(selection["super_skill_ids"])
    if len(catalog_rows) != 105 or len(catalog) != 105:
        raise SystemExit("expected exact 105-entry active catalog")
    if generated_ids != set(SCENES) or len(generated_ids) != 30:
        raise SystemExit("super-skill art scenes must exactly match the selected 30 modules")
    if not generated_ids.issubset(active_ids):
        raise SystemExit("selected super skills are missing from active catalog")

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
        for module_id in active_ids - generated_ids
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

    for module_id in sorted(generated_ids):
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
        f"Reconciled {len(active_ids)} active WebPs; generated {len(generated_ids)} "
        f"super-skill images; archived {moved} retired WebPs"
    )


if __name__ == "__main__":
    main()
