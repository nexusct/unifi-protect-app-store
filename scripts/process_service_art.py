#!/usr/bin/env python3
"""Convert generated service artwork into a centered transparent WebP.

The image model is instructed to render a contiguous white background. This
processor removes only background-colored pixels connected to the canvas edge,
so light details enclosed by the subject remain intact. The surviving subject
is then cropped, centered, and resized for the marketplace's 48-88 px display.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFilter

OUTPUT_SIZE = 320
CONTENT_SIZE = 288
MAX_INPUT_EDGE = 4096
MIN_INPUT_EDGE = 256
BACKGROUND_TOLERANCE = 52
BACKGROUND_FLOOR = 205
_SENTINEL = (255, 0, 255, 0)


def _edge_background(image: Image.Image) -> tuple[int, int, int, int]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    samples: list[tuple[int, int, int, int]] = []
    steps = 32
    for index in range(steps):
        x = round((width - 1) * index / (steps - 1))
        y = round((height - 1) * index / (steps - 1))
        samples.extend(
            (
                cast(tuple[int, int, int, int], rgba.getpixel((x, 0))),
                cast(tuple[int, int, int, int], rgba.getpixel((x, height - 1))),
                cast(tuple[int, int, int, int], rgba.getpixel((0, y))),
                cast(tuple[int, int, int, int], rgba.getpixel((width - 1, y))),
            )
        )
    channels = list(zip(*samples))
    background = tuple(sorted(channel)[len(channel) // 2] for channel in channels[:3]) + (255,)
    if min(background[:3]) < BACKGROUND_FLOOR:
        raise ValueError(f"edge background must be near white, got {background[:3]}")
    return cast(tuple[int, int, int, int], background)


def remove_edge_background(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if min(width, height) < MIN_INPUT_EDGE or max(width, height) > MAX_INPUT_EDGE:
        raise ValueError(
            f"input dimensions must be between {MIN_INPUT_EDGE} and {MAX_INPUT_EDGE}px, got {width}x{height}"
        )

    _edge_background(rgba)
    working = rgba.copy()
    seeds = (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    )
    for seed in seeds:
        pixel = cast(tuple[int, int, int, int], working.getpixel(seed))
        if pixel[:3] == _SENTINEL[:3] or min(pixel[:3]) >= BACKGROUND_FLOOR:
            ImageDraw.floodfill(
                working,
                seed,
                _SENTINEL,
                thresh=BACKGROUND_TOLERANCE,
            )

    # Flood-filled background pixels carry alpha zero; enclosed subject pixels
    # retain their original alpha. A tiny blur softens antialiased cutout edges.
    alpha = working.getchannel("A").filter(ImageFilter.GaussianBlur(radius=0.7))
    rgba.putalpha(alpha)
    return rgba


def center_subject(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("no visible subject remains after background removal")

    subject = image.crop(bounds)
    scale = min(CONTENT_SIZE / subject.width, CONTENT_SIZE / subject.height)
    resized = subject.resize(
        (max(1, round(subject.width * scale)), max(1, round(subject.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (OUTPUT_SIZE, OUTPUT_SIZE), (0, 0, 0, 0))
    x = (OUTPUT_SIZE - resized.width) // 2
    y = (OUTPUT_SIZE - resized.height) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas


def process(source: Path, destination: Path) -> None:
    with Image.open(source) as original:
        rendered = center_subject(remove_edge_background(original))

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=".webp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        rendered.save(
            temporary,
            format="WEBP",
            quality=82,
            method=6,
            exact=True,
            exif=b"",
            xmp=b"",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.suffix.lower() != ".webp":
        parser.error("destination must end in .webp")
    process(args.source, args.destination)


if __name__ == "__main__":
    main()
