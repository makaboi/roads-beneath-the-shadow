#!/usr/bin/env python3
"""Slice generated atlases and draw original story props at native resolution.

The game loads the resulting PNGs directly; Pillow is a development tool only.
Run with --environment-atlas PATH and optionally --encounter-atlas PATH.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "roads_beneath_shadow" / "pixel_assets"
SIZE = (320, 240)
ENVIRONMENTS = ("title", "tavern", "marsh", "camp", "rider", "seal")
ENCOUNTERS = ("orc", "warg", "ghorak", "troll", "ranger", "tavern-interior")
PALETTE = {
    "black": "#080b0b", "dark": "#121a1a", "teal": "#253b3b",
    "mist": "#48605c", "stone": "#645b43", "bronze": "#9f7842",
    "amber": "#d29945", "gold": "#efbe68", "bone": "#f3d6a3",
}


def slice_atlas(path: Path, names: tuple[str, ...], palette: Image.Image | None = None) -> None:
    """Extract equal 3x2 panels and keep nearest-neighbor pixel edges."""
    atlas = Image.open(path).convert("RGB")
    if palette is None:
        palette = atlas.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    for index, name in enumerate(names):
        column, row = index % 3, index // 3
        bounds = (
            round(column * atlas.width / 3), round(row * atlas.height / 2),
            round((column + 1) * atlas.width / 3), round((row + 1) * atlas.height / 2),
        )
        panel = atlas.crop(bounds).resize(SIZE, Image.Resampling.NEAREST)
        panel = panel.quantize(palette=palette, dither=Image.Dither.NONE)
        panel.save(DEST / f"{name}.png", optimize=True)


def prop_stage() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """An original stone display plinth, drawn with integer pixel clusters."""
    image = Image.new("RGB", SIZE, PALETTE["black"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 307, 226), outline=PALETTE["teal"])
    draw.rectangle((16, 16, 303, 222), outline=PALETTE["dark"])
    for y in range(32, 196, 22):
        offset = 16 if (y // 22) % 2 else 0
        for x in range(20 + offset, 300, 40):
            draw.line((x, y, min(x + 36, 299), y), fill=PALETTE["dark"])
            draw.line((x, y, x, y + 18), fill=PALETTE["dark"])
    draw.polygon(((74, 181), (246, 181), (277, 215), (44, 215)), fill=PALETTE["dark"])
    draw.line((74, 181, 246, 181), fill=PALETTE["stone"], width=2)
    draw.line((46, 214, 274, 214), fill=PALETTE["teal"], width=2)
    rng = random.Random(1428)
    for _ in range(48):
        x, y = rng.randrange(25, 298), rng.randrange(23, 178)
        draw.point((x, y), fill=PALETTE["dark"])
    return image, draw


def star(draw: ImageDraw.ImageDraw, center: tuple[int, int], broken: bool = False) -> None:
    x, y = center
    rays = [((x-6,y-12),(x,y-66),(x+6,y-12)),
            ((x+12,y-6),(x+66,y),(x+12,y+6)),
            ((x+6,y+12),(x,y+66),(x-6,y+12)),
            ((x-12,y+6),(x-66,y),(x-12,y-6)),
            ((x+4,y-12),(x+43,y-43),(x+12,y-4)),
            ((x+12,y+4),(x+43,y+43),(x+4,y+12)),
            ((x-4,y+12),(x-43,y+43),(x-12,y+4)),
            ((x-12,y-4),(x-43,y-43),(x-4,y-12))]
    for index, points in enumerate(rays):
        if broken and index in (1, 4):
            continue
        draw.polygon(points, fill=PALETTE["bronze"])
        draw.line((x,y,points[1][0],points[1][1]),fill=PALETTE["gold"],width=2)
    draw.polygon(((x-12,y-7),(x-7,y-12),(x+7,y-12),(x+12,y-7),
                  (x+12,y+7),(x+7,y+12),(x-7,y+12),(x-12,y+7)),
                 fill=PALETTE["bronze"],outline=PALETTE["gold"])
    draw.rectangle((x-4,y-4,x+4,y+4), fill=PALETTE["bone"])
    if broken:
        draw.line(((x+3,y-12),(x-1,y-5),(x+5,y+1),(x-2,y+8),(x+1,y+12)),
                  fill=PALETTE["black"],width=3)
        draw.polygon(((x+43,y-34),(x+54,y-46),(x+48,y-27)),fill=PALETTE["bronze"])


def draw_props() -> None:
    for name in ("key", "broken-key"):
        image, draw = prop_stage()
        star(draw, (160, 111), broken=name == "broken-key")
        image.save(DEST / f"{name}.png", optimize=True)

    image, draw = prop_stage()
    draw.polygon(((103, 162),(212, 53),(218, 47),(216, 57),(111, 170)),fill=PALETTE["mist"])
    draw.line((108, 164,214, 51), fill=PALETTE["bone"],width=3)
    draw.line((104, 164,206, 56), fill=PALETTE["stone"],width=2)
    draw.line((90, 149,120, 179), fill=PALETTE["bronze"],width=6)
    draw.line((91, 150,119, 178), fill=PALETTE["gold"],width=2)
    draw.line((101, 171,83, 189), fill=PALETTE["stone"],width=6)
    draw.rectangle((78,186,85,193), fill=PALETTE["bronze"])
    draw.polygon(((173,94),(181,93),(178,100),(185,100),(181,105),(190,104),(184,111),(177,112)),
                 fill=PALETTE["black"])
    image.save(DEST / "sword.png", optimize=True)

    image, draw = prop_stage()
    draw.polygon(((75,54),(237,51),(244,176),(80,181),(76,162)),fill=PALETTE["bronze"])
    draw.rectangle((83,59,233,173),fill=PALETTE["amber"])
    draw.line(((88,161),(111,145),(117,124),(141,118),(152,99),(176,87),(204,71)),fill=PALETTE["dark"],width=3)
    for x,y in ((99,91),(110,104),(182,131),(211,139),(201,122)):
        draw.polygon(((x-8,y+6),(x,y-8),(x+8,y+6)),fill=PALETTE["stone"])
        draw.line((x,y-8,x+8,y+6),fill=PALETTE["bone"])
    draw.line(((89,167),(106,156),(129,158),(144,151),(168,162),(194,161),(226,166)),fill=PALETTE["teal"],width=2)
    for x,y in ((114,144),(152,99),(201,73)):
        draw.rectangle((x-3,y-3,x+3,y+3),fill=PALETTE["bone"],outline=PALETTE["dark"])
    draw.rectangle((83,59,233,173),outline=PALETTE["gold"])
    image.save(DEST / "map.png", optimize=True)

    image, draw = prop_stage()
    draw.line((160,23,160,58),fill=PALETTE["stone"],width=3)
    draw.arc((151,53,169,71),180,360,fill=PALETTE["bronze"],width=3)
    draw.polygon(((146,72),(174,72),(187,90),(133,90)),fill=PALETTE["bronze"])
    draw.polygon(((137,93),(183,93),(180,155),(140,155)),fill=PALETTE["stone"])
    draw.rectangle((144,96,176,149),fill=PALETTE["amber"])
    draw.polygon(((150,143),(148,131),(157,125),(156,115),(160,110),(164,122),(169,129),(168,142)),fill=PALETTE["gold"])
    draw.rectangle((155,131,163,143),fill=PALETTE["bone"])
    draw.line((160,93,160,150),fill=PALETTE["bronze"],width=3)
    draw.polygon(((137,153),(182,153),(187,161),(132,161)),fill=PALETTE["bronze"])
    draw.line((136,161,184,161),fill=PALETTE["gold"])
    image.save(DEST / "lantern.png", optimize=True)

    image, draw = prop_stage()
    for x in (48,180):
        draw.line((x+45,23,x+45,55),fill=PALETTE["stone"],width=3)
        draw.polygon(((x+2,80),(x+44,52),(x+86,80)),fill=PALETTE["teal"],outline=PALETTE["mist"])
        draw.rectangle((x+1,81,x+87,179),fill=PALETTE["dark"],outline=PALETTE["stone"])
        draw.ellipse((x+32,111,x+52,131),fill=PALETTE["stone"])
        draw.polygon(((x+33,130),(x+21,160),(x+16,170),(x+66,170),(x+57,151),(x+51,130)),fill=PALETTE["teal"])
        for bar in range(x+3,x+88,14):
            draw.line((bar,81,bar,178),fill=PALETTE["mist"],width=2)
        draw.line((x+1,103,x+86,103),fill=PALETTE["stone"],width=3)
        draw.line((x+1,157,x+86,157),fill=PALETTE["stone"],width=3)
        draw.rectangle((x-2,178,x+90,183),fill=PALETTE["stone"])
    image.save(DEST / "cages.png", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-atlas", type=Path)
    parser.add_argument("--encounter-atlas", type=Path)
    args = parser.parse_args()
    DEST.mkdir(parents=True,exist_ok=True)
    palette = None
    if args.environment_atlas:
        palette = Image.open(args.environment_atlas).convert("RGB").quantize(colors=32)
        slice_atlas(args.environment_atlas,ENVIRONMENTS,palette)
    if args.encounter_atlas:
        slice_atlas(args.encounter_atlas,ENCOUNTERS,palette)
    draw_props()
    manifest = {
        "format": 1, "resolution": list(SIZE), "scaling": "nearest-neighbor",
        "palette_colors_per_scene": 32,
        "environment_scenes": list(ENVIRONMENTS),
        "encounter_scenes": list(ENCOUNTERS),
        "original_pixel_props": ["key", "broken-key", "sword", "map", "lantern", "cages"],
        "art_direction": "Gothic dark fantasy: charcoal, sepia, bone, amber and muted teal",
        "source_atlases": "Generated with OpenAI image generation; original atlases retained outside the package.",
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
