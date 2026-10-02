#!/usr/bin/env python3
"""Compile one image-generated story scene, optionally sharing an atlas palette.

The original input stays unchanged. This performs only native-grid conversion;
it does not draw, retouch, regenerate props, or edit the asset manifest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "roads_beneath_shadow" / "pixel_assets"
SIZE = (320, 240)


def build(source: Path, name: str, destination: Path = DESTINATION, *, palette_source: Path | None = None) -> dict:
    if re.fullmatch(r"[a-z0-9-]+", name) is None or name.startswith("world-"):
        raise ValueError("Use a scene name, without a path or world-atlas prefix")
    source_bytes = source.read_bytes()
    with Image.open(source) as original:
        dimensions = original.size
        native = original.convert("RGB").resize(SIZE, Image.Resampling.NEAREST)
    conversion = {
        "script": "scripts/build_story_scene.py", "resize": "nearest-neighbor",
        "native_size": list(SIZE), "colors": 32, "dither": "none",
    }
    if palette_source is not None:
        with Image.open(palette_source) as palette_image:
            palette = palette_image.convert("RGB").quantize(colors=32)
        native = native.quantize(palette=palette, dither=Image.Dither.NONE)
        conversion.update({
            "palette_source_name": palette_source.name,
            "palette_source_sha256": hashlib.sha256(palette_source.read_bytes()).hexdigest(),
        })
    else:
        native = native.quantize(colors=32, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{name}.png"
    native.save(target, optimize=True)
    return {
        "generator": "OpenAI image generation", "source_name": source.name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_dimensions": list(dimensions), "generated_on": datetime.now(timezone.utc).date().isoformat(),
        "conversion": conversion, "native_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--palette-source", type=Path)
    parser.add_argument("--provenance", type=Path)
    arguments = parser.parse_args()
    record = build(arguments.source, arguments.name, arguments.destination, palette_source=arguments.palette_source)
    if arguments.provenance:
        arguments.provenance.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scene": arguments.name, "native_sha256": record["native_sha256"]}))


if __name__ == "__main__":
    main()
