#!/usr/bin/env python3
"""Pack image-generated actors onto the game's native battle sprite grid.

Source images remain unchanged. Transparent gutters identify the six authored
figures; one common nearest-neighbor scale preserves their adult proportions.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "roads_beneath_shadow" / "pixel_assets"
CAST = ("wayfarer", "scout", "healer", "mara", "tobin", "calenor")
CELL = (40, 48)
SIZE = (120, 96)


def _horizontal_figures(alpha: Image.Image) -> list[tuple[int, int]]:
    """Find the authored column silhouettes, excluding transparent gutters."""
    runs: list[list[int]] = []
    for x in range(alpha.width):
        if alpha.crop((x, 0, x + 1, alpha.height)).getbbox() is None:
            continue
        if not runs or x > runs[-1][1] + 1:
            runs.append([x, x])
        else:
            runs[-1][1] = x
    # Single isolated alpha pixels must not silently become a seventh actor.
    if len(runs) != 3:
        raise ValueError("Each cast row must contain exactly three separated silhouettes")
    return [(left, right + 1) for left, right in runs]


def build(source: Path, destination: Path = DESTINATION) -> dict:
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        original = original.convert("RGBA")
    alpha = original.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    original.putalpha(alpha)
    figures: list[Image.Image] = []
    bounds: list[list[int]] = []
    for row in range(2):
        top, bottom = round(row * original.height / 2), round((row + 1) * original.height / 2)
        row_alpha = alpha.crop((0, top, original.width, bottom))
        for left, right in _horizontal_figures(row_alpha):
            box = alpha.crop((left, top, right, bottom)).getbbox()
            if box is None:
                raise ValueError("Empty actor cell")
            bounds.append([left + box[0], top + box[1], left + box[2], top + box[3]])
            figures.append(original.crop(bounds[-1]))
    scale = min(32 / max(figure.width for figure in figures), 44 / max(figure.height for figure in figures))
    native = Image.new("RGBA", SIZE)
    for index, figure in enumerate(figures):
        size = (max(1, round(figure.width * scale)), max(1, round(figure.height * scale)))
        figure = figure.resize(size, Image.Resampling.NEAREST)
        x = (index % 3) * CELL[0] + (CELL[0] - size[0]) // 2
        y = (index // 3) * CELL[1] + 45 - size[1]
        native.paste(figure, (x, y))
    native_alpha = native.getchannel("A")
    palette = native.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    native = palette.convert("RGBA")
    native.putalpha(native_alpha)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "world-battle-cast.png"
    native.save(target, optimize=True)
    return {
        "generator": "OpenAI image generation",
        "source_name": source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dimensions": list(original.size),
        "source_silhouette_bounds": bounds,
        "native_dimensions": list(SIZE),
        "cell_dimensions": list(CELL),
        "cast": list(CAST),
        "feet_baseline": 44,
        "conversion": {"script": "scripts/build_battle_cast.py", "resize": "nearest-neighbor", "scale": "shared across all actors", "colors": 32, "dither": "none", "alpha": "binary"},
        "native_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def build_teren(source: Path, destination: Path = DESTINATION) -> dict:
    """Compile a single Ranger while keeping the party cast's pixel geometry."""
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        original = original.convert("RGBA")
    alpha = original.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("Ranger source has no opaque silhouette")
    original.putalpha(alpha)
    figure = original.crop(bounds)
    scale = min(32 / figure.width, 44 / figure.height)
    size = (max(1, round(figure.width * scale)), max(1, round(figure.height * scale)))
    figure = figure.resize(size, Image.Resampling.NEAREST)
    native = Image.new("RGBA", CELL)
    native.paste(figure, ((CELL[0] - size[0]) // 2, 45 - size[1]))
    native_alpha = native.getchannel("A")
    colors = native.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    native = colors.convert("RGBA")
    native.putalpha(native_alpha)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "world-battle-teren.png"
    native.save(target, optimize=True)
    return {
        "generator": "OpenAI image generation", "source_name": source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dimensions": list(original.size), "source_silhouette_bounds": list(bounds),
        "native_dimensions": list(CELL), "cast": ["teren"], "feet_baseline": 44,
        "conversion": {"script": "scripts/build_battle_cast.py", "option": "--teren", "resize": "nearest-neighbor", "colors": 32, "dither": "none", "alpha": "binary"},
        "native_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--teren", action="store_true", help="Compile the separate 40x48 False Ranger")
    arguments = parser.parse_args()
    metadata = build_teren(arguments.source, arguments.destination) if arguments.teren else build(arguments.source, arguments.destination)
    metadata["generated_on"] = datetime.now(timezone.utc).date().isoformat()
    if arguments.provenance:
        arguments.provenance.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    name = "world-battle-teren.png" if arguments.teren else "world-battle-cast.png"
    print(json.dumps({"cast_asset": str(arguments.destination / name), "native_sha256": metadata["native_sha256"]}))


if __name__ == "__main__":
    main()
