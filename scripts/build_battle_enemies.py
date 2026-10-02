#!/usr/bin/env python3
"""Pack eight generated transparent enemy silhouettes into native battle cells.

The source must contain four columns and two rows, ordered scout, captain,
archer, sapper, warg, Ghorak, troll, rider. Alpha components preserve weapons
or cloaks crossing the generated source's grid boundaries. No authored shape
is trimmed; nearest-neighbor resizing preserves the source's pixel clusters.
Pillow is needed only when rebuilding the packaged atlas.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "roads_beneath_shadow" / "pixel_assets" / "world-battle-enemies.png"
NAMES = ("orc-scout", "orc-captain", "orc-archer", "orc-sapper", "warg", "ghorak", "troll", "rider")
CELL = (40, 48)
SIZE = (160, 96)
BASELINE = 44


def component_bounds(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Find the eight complete opaque silhouettes without cutting at cell edges."""
    alpha = image.getchannel("A")
    pixels = alpha.load()
    width, height = image.size
    seen = bytearray(width * height)
    components: list[tuple[int, tuple[int, int, int, int]]] = []
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if seen[index] or pixels[x, y] < 128:
                continue
            queue = deque([(x, y)])
            seen[index] = 1
            left = right = x
            top = bottom = y
            count = 0
            while queue:
                px, py = queue.pop()
                count += 1
                left, right = min(left, px), max(right, px)
                top, bottom = min(top, py), max(bottom, py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    neighbor = ny * width + nx
                    if not seen[neighbor] and pixels[nx, ny] >= 128:
                        seen[neighbor] = 1
                        queue.append((nx, ny))
            components.append((count, (left, top, right + 1, bottom + 1)))

    major = sorted(components, reverse=True)[:8]
    if len(major) != 8 or min(count for count, _bounds in major) < 500:
        raise ValueError("The enemy source must contain eight separated alpha silhouettes")
    bounds = [bounds for _count, bounds in major]
    bounds.sort(key=lambda box: (box[1] + box[3]) / 2)
    # A short wolf has a lower center than the other bottom-row creatures;
    # split by vertical order before sorting each complete row left to right.
    return sorted(bounds[:4], key=lambda box: box[0]) + sorted(bounds[4:], key=lambda box: box[0])


def pack(source: Path, output: Path, *, metadata: Path | None = None) -> dict:
    """Pack with one shared palette, binary alpha, and a stable foot baseline."""
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        image = original.convert("RGBA")
    if image.getchannel("A").getextrema()[0] != 0:
        raise ValueError("The enemy source must have a transparent background")
    bounds = component_bounds(image)
    image.putalpha(image.getchannel("A").point(lambda value: 255 if value >= 128 else 0))
    palette = image.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    atlas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    report = {
        "generator": "OpenAI image generation",
        "source_name": source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dimensions": list(image.size),
        "native_dimensions": list(SIZE),
        "cell_dimensions": list(CELL),
        "baseline": BASELINE,
        "conversion": {"script": "scripts/build_battle_enemies.py", "resize": "nearest-neighbor", "colors": 32, "dither": "none", "alpha": "binary"},
        "cells": {},
    }
    for index, (name, box) in enumerate(zip(NAMES, bounds, strict=True)):
        cropped = image.crop(box)
        # Humanoids share a 42-pixel height. Broad beasts need two pixels
        # beside the body for the renderer's hurt and attack leans.
        maximum_width = 36 if name in {"warg", "troll", "rider"} else 38
        factor = min(42 / cropped.height, maximum_width / cropped.width)
        width = min(maximum_width, max(1, round(cropped.width * factor)))
        height = min(42, max(1, round(cropped.height * factor)))
        native = cropped.resize((width, height), Image.Resampling.NEAREST)
        alpha = native.getchannel("A")
        colored = native.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).convert("RGBA")
        colored.putalpha(alpha)
        column, row = index % 4, index // 4
        x = column * CELL[0] + (CELL[0] - width) // 2
        y = row * CELL[1] + BASELINE + 1 - height
        atlas.alpha_composite(colored, (x, y))
        report["cells"][name] = {"index": index, "source_bounds": list(box), "native_bounds": [x - column * CELL[0], y - row * CELL[1], x - column * CELL[0] + width, BASELINE + 1], "native_size": [width, height]}

    # Transparent RGB values cannot create a 33rd visible palette entry or a
    # colored fringe when SDL uploads and scales the native cells.
    pixel_data = atlas.get_flattened_data() if hasattr(atlas, "get_flattened_data") else atlas.getdata()
    data = [(red, green, blue, alpha) if alpha else (0, 0, 0, 0) for red, green, blue, alpha in pixel_data]
    atlas.putdata(data)
    colors = {pixel[:3] for pixel in data if pixel[3]}
    if len(colors) > 32 or {pixel[3] for pixel in data} != {0, 255}:
        raise ValueError("The packed enemy atlas must have 32 colors or fewer and binary alpha")
    output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output, optimize=True)
    report["native_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    report["visible_colors"] = len(colors)
    report["output"] = str(output)
    if metadata:
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=DEST)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    report = pack(args.source, args.output, metadata=args.metadata)
    print(json.dumps({"output": report["output"], "visible_colors": report["visible_colors"], "cells": report["cells"]}, indent=2))


if __name__ == "__main__":
    main()
