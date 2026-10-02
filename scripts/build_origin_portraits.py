#!/usr/bin/env python3
"""Compile an image-generated portrait atlas for the offline pixel renderer.

The authored source stays unchanged. This build step only reduces it to the
native sprite grid and a shared, undithered palette with binary transparency.
Pillow is a development dependency; players only load the resulting PNG.
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
PORTRAITS = ("wayfarer", "scout", "healer")
CELL = (64, 80)
SIZE = (CELL[0] * len(PORTRAITS), CELL[1])


def build(source: Path, destination: Path = DESTINATION) -> dict:
    """Pack the three source cells without changing their authored content."""
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        original = original.convert("RGBA")
        source_size = original.size
        if abs(original.width / original.height - SIZE[0] / SIZE[1]) > 0.08:
            raise ValueError("Portrait source must contain three equal 4:5 cells")
        native = original.resize(SIZE, Image.Resampling.NEAREST)
    alpha = native.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    colors = native.convert("RGB").quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    native = colors.convert("RGBA")
    native.putalpha(alpha)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "world-origin-portraits.png"
    native.save(target, optimize=True)
    return {
        "generator": "OpenAI image generation",
        "source_name": source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dimensions": list(source_size),
        "native_dimensions": list(SIZE),
        "cell_dimensions": list(CELL),
        "portraits": list(PORTRAITS),
        "conversion": {"script": "scripts/build_origin_portraits.py", "resize": "nearest-neighbor", "colors": 32, "dither": "none", "alpha": "binary"},
        "native_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--provenance", type=Path)
    arguments = parser.parse_args()
    metadata = build(arguments.source, arguments.destination)
    metadata["generated_on"] = datetime.now(timezone.utc).date().isoformat()
    if arguments.provenance:
        arguments.provenance.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"portrait_asset": str(arguments.destination / "world-origin-portraits.png"), "native_sha256": metadata["native_sha256"]}))


if __name__ == "__main__":
    main()
