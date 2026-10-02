#!/usr/bin/env python3
"""Compile three image-generated battle locations onto a 320x240 pixel grid.

The source strip is retained unchanged. Wide panels are fitted by a documented
crop, never stretched; each location keeps its own restrained 32-color palette.
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
LOCATIONS = ("marsh-battle", "seal-vault-battle", "dead-road-battle")
SIZE = (320, 240)


def build(source: Path, destination: Path = DESTINATION) -> dict:
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        original = original.convert("RGB")
    destination.mkdir(parents=True, exist_ok=True)
    records = {}
    for index, name in enumerate(LOCATIONS):
        left, right = round(index * original.width / 3), round((index + 1) * original.width / 3)
        width = right - left
        height = min(original.height, round(width * SIZE[1] / SIZE[0]))
        # The authored strip places its doorway/arches above a deep floor.
        # Keep those landmarks and the middle floor rather than bottom rubble.
        top = min(40, original.height - height)
        crop = (left, top, right, top + height)
        image = original.crop(crop).resize(SIZE, Image.Resampling.NEAREST)
        image = image.quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        target = destination / f"{name}.png"
        image.save(target, optimize=True)
        records[name] = {
            "generator": "OpenAI image generation", "source_name": source.name,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_dimensions": list(original.size), "source_crop": list(crop),
            "native_dimensions": list(SIZE), "ground_y": 170,
            "conversion": {"script": "scripts/build_battle_locations.py", "resize": "nearest-neighbor", "colors": 32, "dither": "none", "aspect": "crop to 4:3"},
            "native_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--provenance", type=Path)
    arguments = parser.parse_args()
    metadata = build(arguments.source, arguments.destination)
    for record in metadata.values():
        record["generated_on"] = datetime.now(timezone.utc).date().isoformat()
    if arguments.provenance:
        arguments.provenance.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"battle_backgrounds": list(metadata)}))


if __name__ == "__main__":
    main()
