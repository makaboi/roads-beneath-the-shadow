"""Generate original, reproducible pixel tiles and animated story sprites.

Pillow is a development dependency only.  The game loads the resulting PNGs.
This artwork is authored as discrete pixels, with no resampling, photographs,
third-party sprite packs, or runtime image-generation requirement.
"""

from __future__ import annotations

from pathlib import Path
import random
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roads_beneath_shadow.pixel_world import TILE, WORLD_MAPS, WORLD_SIZE  # noqa: E402

DESTINATION = ROOT / "roads_beneath_shadow" / "pixel_assets"

# A shared art direction links warm Bree wood to the colder buried roads.
COLORS = {
    "void": "#10151b", "shadow": "#0c1115", "ink": "#172027",
    "wood0": "#332922", "wood1": "#44352a", "wood2": "#594432",
    "wood3": "#74583b", "wood4": "#96724a", "wood5": "#b68b55",
    "stone0": "#28343a", "stone1": "#374448", "stone2": "#485452",
    "stone3": "#626963", "stone4": "#848578", "stone5": "#a6a394",
    "grass0": "#202f2b", "grass1": "#2c3c30", "grass2": "#3b4d38",
    "grass3": "#4a5d41", "moss": "#576449", "leaf": "#738368",
    "roof0": "#28343d", "roof1": "#37484f", "roof2": "#465d60",
    "roof3": "#627575", "water0": "#1b2b36", "water1": "#263c46",
    "water2": "#35515a", "water3": "#536f70", "water4": "#809896",
    "straw0": "#54452e", "straw1": "#725d3a", "straw2": "#947849",
    "amber0": "#856335", "amber1": "#c18b46", "amber2": "#e5b65f",
    "amber3": "#f6d690", "bone": "#d2c4a1", "silver": "#aeb8ae",
    "teal0": "#294c49", "teal1": "#46716a", "teal2": "#71958a",
    "cloth0": "#202731", "cloth1": "#343e46", "cloth2": "#4e5b5b",
    "skin0": "#795b43", "skin1": "#ad8660", "skin2": "#d1aa7a",
    "blood": "#854239", "purple0": "#3d3245", "purple1": "#685063",
}


def color(name: str) -> str:
    return COLORS.get(name, name)


def rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], name: str) -> None:
    draw.rectangle(box, fill=color(name))


def line(draw: ImageDraw.ImageDraw, points: tuple[int, ...], name: str) -> None:
    draw.line(points, fill=color(name))


def _floor(draw: ImageDraw.ImageDraw, x: int, y: int, glyph: str, key: str, rng: random.Random) -> None:
    px, py = x * TILE, y * TILE
    if key == "pony":
        rect(draw, (px, py, px + 15, py + 15), "wood1")
        for row in range(0, 16, 5):
            shade = rng.choice(("wood1", "wood1", "wood2", "wood0"))
            rect(draw, (px, py + row, px + 15, min(py + row + 3, py + 15)), shade)
            line(draw, (px, py + row + 4, px + 15, py + row + 4), "wood0")
            if rng.randrange(3) == 0:
                line(draw, (px + 3, py + row + 1, px + 10, py + row + 1), "wood3")
        seam = 3 if (x + y) % 2 else 12
        line(draw, (px + seam, py, px + seam, py + 3), "wood0")
        draw.point((px + seam + 2, py + 2), fill=color("wood4"))
    elif key == "bree" and glyph not in "=+":
        rect(draw, (px, py, px + 15, py + 15), "grass0")
        for _ in range(12):
            ax, ay = px + rng.randrange(14), py + rng.randrange(14)
            rect(draw, (ax, ay, ax + rng.randrange(1, 3), ay + 1), rng.choice(("grass1", "grass2", "grass3")))
            if rng.randrange(4) == 0:
                draw.point((ax + 1, ay - 1), fill=color("moss"))
    else:
        rect(draw, (px, py, px + 15, py + 15), "stone0")
        for row in range(0, 16, 8):
            for column in range(-4 if (y * 2 + row // 8) % 2 else 0, 16, 8):
                left = max(px, px + column)
                right = min(px + 15, px + column + 6)
                if right < left:
                    continue
                shade = rng.choice(("stone1", "stone1", "stone1", "stone1", "stone2", "stone0"))
                rect(draw, (left, py + row, right, py + row + 6), shade)
                if shade != "stone0":
                    line(draw, (left, py + row, right, py + row), "stone2")
                if rng.randrange(5) == 0:
                    line(draw, (left + 2, py + row + 3, min(right, left + 4), py + row + 5), "stone0")
        if key == "bree" and rng.randrange(3) == 0:
            draw.ellipse((px + 3, py + 5, px + 12, py + 9), fill=color("water1"))
            line(draw, (px + 5, py + 6, px + 9, py + 6), "water2")
        if key in {"hall", "wayhouse", "lantern"} and rng.randrange(5) == 0:
            draw.point((px + 2, py + 11), fill=color("moss"))


def _wall(draw: ImageDraw.ImageDraw, px: int, py: int, key: str, rng: random.Random) -> None:
    rect(draw, (px, py, px + 15, py + 15), "shadow")
    if key == "pony":
        rect(draw, (px + 1, py, px + 14, py + 10), "wood2")
        rect(draw, (px + 2, py + 1, px + 13, py + 3), "wood3")
        line(draw, (px + 3, py + 5, px + 11, py + 5), "wood0")
        rect(draw, (px + 1, py + 10, px + 14, py + 12), "wood0")
        line(draw, (px + 2, py + 10, px + 13, py + 10), "wood4")
    else:
        for row, offset in ((0, 0), (6, -6)):
            for column in range(offset, 16, 9):
                left, right = max(px, px + column), min(px + 15, px + column + 7)
                rect(draw, (left, py + row, right, py + row + 4), rng.choice(("stone1", "stone2", "stone2")))
                line(draw, (left, py + row, right, py + row), "stone3")
        line(draw, (px, py + 11, px + 15, py + 11), "stone0")
        if rng.randrange(3) == 0:
            rect(draw, (px + 9, py + 6, px + 12, py + 8), "moss")


def _shelf(draw: ImageDraw.ImageDraw, px: int, py: int) -> None:
    rect(draw, (px, py + 2, px + 15, py + 15), "shadow")
    rect(draw, (px, py, px + 15, py + 12), "wood0")
    for y in (4, 10):
        for x in range(2, 14, 3):
            rect(draw, (px + x, py + y - 3, px + x + 1, py + y), ("wood4", "blood", "teal0", "bone")[(x + y) % 4])
        line(draw, (px, py + y + 1, px + 15, py + y + 1), "wood3")


def _tree(draw: ImageDraw.ImageDraw, px: int, py: int, rng: random.Random) -> None:
    draw.ellipse((px - 2, py + 9, px + 20, py + 16), fill=color("shadow"))
    rect(draw, (px + 6, py + 3, px + 9, py + 13), "wood0")
    line(draw, (px + 7, py + 6, px + 7, py + 12), "wood3")
    clusters = ((0, -7, 13, 4), (5, -12, 16, -2), (-3, -3, 16, 10), (6, -5, 20, 7))
    for index, (x1, y1, x2, y2) in enumerate(clusters):
        draw.ellipse((px + x1, py + y1, px + x2, py + y2), fill=color("grass0" if index == 2 else "grass1"))
        for _ in range(8):
            ax, ay = rng.randint(px + x1 + 2, px + x2 - 2), rng.randint(py + y1 + 2, py + y2 - 2)
            rect(draw, (ax, ay, ax + 2, ay + 1), rng.choice(("grass2", "grass3", "moss")))
    line(draw, (px + 5, py - 8, px + 10, py - 8), "leaf")


def _roof(draw: ImageDraw.ImageDraw, px: int, py: int, glyph: str, grid: tuple[str, ...], x: int, y: int) -> None:
    straw = glyph == "R"
    rect(draw, (px, py, px + 15, py + 15), "straw0" if straw else "roof0")
    for row in range(0, 16, 4):
        line(draw, (px, py + row, px + 15, py + row), "straw1" if straw else "roof2")
        for column in range(2 + ((row // 4) % 2) * 4, 16, 8):
            line(draw, (px + column, py + row + 1, px + column, py + row + 3), "straw2" if straw else "roof1")
    if y + 1 < len(grid) and grid[y + 1][x] not in {glyph, "+"}:
        rect(draw, (px, py + 11, px + 15, py + 15), "wood1")
        line(draw, (px, py + 11, px + 15, py + 11), "wood4")
        for ax in (1, 13):
            line(draw, (px + ax, py + 12, px + ax, py + 15), "wood0")
        if x % 2:
            rect(draw, (px + 5, py + 12, px + 9, py + 14), "amber1")
            line(draw, (px + 7, py + 12, px + 7, py + 14), "wood0")


def _gable_roof(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, straw: bool = False) -> None:
    """Two visible roof planes with a ridge and a timber south facade."""
    left, top, right, bottom = box
    ridge = top + (bottom - top) // 2 - 5
    upper = "straw1" if straw else "roof2"
    lower = "straw0" if straw else "roof1"
    edge = "straw2" if straw else "roof3"
    dark = "wood0" if straw else "roof0"
    rect(draw, (left, top, right, bottom), dark)
    rect(draw, (left + 1, top + 1, right - 1, ridge - 1), upper)
    rect(draw, (left + 1, ridge + 2, right - 1, bottom - 12), lower)
    for yy in range(top + 3, bottom - 11, 4):
        line(draw, (left + 2, yy, right - 2, yy), "straw0" if straw else "roof0")
        line(draw, (left + 2, yy - 1, right - 2, yy - 1), "straw2" if straw and yy < ridge else ("straw1" if straw else ("roof3" if yy < ridge else "roof2")))
        shift = ((yy - top) // 4 % 2) * 4
        for xx in range(left + 6 + shift, right - 3, 8):
            line(draw, (xx, yy, xx, yy + 2), dark)
    rect(draw, (left, ridge, right, ridge + 2), dark)
    line(draw, (left + 1, ridge, right - 1, ridge), edge)
    for xx in range(left + 2, right - 1, 4):
        draw.point((xx, ridge + 1), fill=color(upper))
    # The timber facade and eaves establish a clear lower edge to the house.
    rect(draw, (left, bottom - 11, right, bottom), "wood1")
    rect(draw, (left, bottom - 12, right, bottom - 10), "wood0")
    line(draw, (left, bottom - 12, right, bottom - 12), "wood4")
    for xx in range(left + 2, right, 16):
        line(draw, (xx, bottom - 9, xx, bottom), "wood0")
        line(draw, (xx + 1, bottom - 9, xx + 1, bottom), "wood3")
    for xx in range(left + 8, right - 8, 24):
        rect(draw, (xx, bottom - 8, xx + 8, bottom - 2), "wood0")
        rect(draw, (xx + 1, bottom - 7, xx + 7, bottom - 3), "amber1")
        line(draw, (xx + 4, bottom - 7, xx + 4, bottom - 3), "wood1")
    # Roof end caps and braces give each building its own silhouette.
    line(draw, (left, top, left, bottom - 12), dark)
    line(draw, (right, top, right, bottom - 12), dark)
    line(draw, (left + 1, top + 1, left + 1, ridge), edge)
    line(draw, (left + 3, bottom - 8, left + 10, bottom - 1), "wood3")
    line(draw, (right - 3, bottom - 8, right - 10, bottom - 1), "wood3")


def _bree_buildings(draw: ImageDraw.ImageDraw) -> None:
    _gable_roof(draw, (32, 32, 95, 79))
    _gable_roof(draw, (32, 144, 111, 207), straw=True)
    _gable_roof(draw, (208, 32, 303, 127))
    # West-side gallery: the attic stair meets the paved lane rather than
    # appearing in the middle of a roof. Its beams are individually painted.
    rect(draw, (192, 32, 207, 127), "wood0")
    rect(draw, (193, 34, 205, 125), "wood1")
    for yy in range(36, 126, 9):
        line(draw, (193, yy, 205, yy), "wood3")
        line(draw, (193, yy + 1, 205, yy + 1), "wood0")
    line(draw, (192, 32, 207, 32), "roof3")
    line(draw, (194, 32, 194, 127), "wood3")
    line(draw, (205, 32, 205, 127), "wood0")
    # A shallow porch roof over the inn's main door, distinct from its attic.
    rect(draw, (224, 128, 287, 133), "roof0")
    for yy in (128, 131):
        line(draw, (224, yy, 287, yy), "roof2")
    rect(draw, (224, 134, 287, 143), "wood1")
    line(draw, (224, 134, 287, 134), "wood4")
    for xx in (225, 285):
        line(draw, (xx, 134, xx, 143), "wood0")
        line(draw, (xx + 1, 134, xx + 1, 143), "wood3")
    # Doors sit on visible walls: attic gallery, kitchen wing and stable.
    for px, py in ((195, 45), (291, 109), (227, 125), (99, 157)):
        rect(draw, (px - 1, py - 1, px + 9, py + 13), "shadow")
        rect(draw, (px, py, px + 7, py + 11), "wood2")
        for xx in (px + 1, px + 4, px + 7):
            line(draw, (xx, py + 1, xx, py + 10), "wood0")
        draw.point((px + 6, py + 6), fill=color("amber2"))
        line(draw, (px - 1, py + 13, px + 9, py + 13), "stone4")
    for yy in (53, 56, 59):
        line(draw, (188, yy, 195, yy), "stone3")
    # Tall stable's right-hand gable timber around Tobin's yard entrance.
    line(draw, (109, 154, 109, 198), "wood4")
    line(draw, (109, 154, 102, 149), "wood3")


def _prop(draw: ImageDraw.ImageDraw, x: int, y: int, glyph: str, key: str, grid: tuple[str, ...], rng: random.Random) -> None:
    px, py = x * TILE, y * TILE
    if glyph == "#":
        _wall(draw, px, py, key, rng)
    elif glyph in {"H", "R"}:
        _roof(draw, px, py, glyph, grid, x, y)
    elif glyph == "V":
        _tree(draw, px, py, rng)
    elif glyph == "~":
        rect(draw, (px, py, px + 15, py + 15), "water0")
        for _ in range(4):
            ax, ay = px + rng.randrange(12), py + rng.randrange(16)
            line(draw, (ax, ay, ax + rng.randrange(1, 4), ay), "water1")
        if x > 0 and grid[y][x - 1] != "~":
            line(draw, (px, py, px, py + 15), "water3")
    elif glyph in {"T", "B", "A"}:
        # Joined table cells share their upper surface while retaining planks.
        rect(draw, (px, py + 3, px + 15, py + 15), "shadow")
        rect(draw, (px, py, px + 15, py + 10), "wood2")
        line(draw, (px, py, px + 15, py), "wood4")
        for offset in (3, 7):
            line(draw, (px, py + offset, px + 15, py + offset), "wood1")
        if glyph == "A":
            line(draw, (px + 3, py + 5, px + 12, py + 5), "silver")
            rect(draw, (px + 2, py + 4, px + 3, py + 6), "wood5")
        elif glyph == "T" and (x + y) % 2 == 0:
            draw.ellipse((px + 5, py + 2, px + 10, py + 6), fill=color("bone"))
            draw.point((px + 7, py + 4), fill=color("wood3"))
        elif glyph == "B":
            rect(draw, (px + 8, py + 3, px + 10, py + 6), "stone4")
            draw.point((px + 11, py + 4), fill=color("bone"))
    elif glyph == "S":
        _shelf(draw, px, py)
    elif glyph == "O":
        draw.ellipse((px + 3, py + 2, px + 13, py + 15), fill=color("wood0"))
        rect(draw, (px + 4, py + 6, px + 12, py + 11), "wood2")
        line(draw, (px + 5, py + 6, px + 5, py + 11), "wood3")
        line(draw, (px + 3, py + 7, px + 13, py + 7), "stone0")
        line(draw, (px + 3, py + 11, px + 13, py + 11), "stone0")
        draw.ellipse((px + 3, py + 2, px + 13, py + 6), outline=color("wood4"))
    elif glyph == "F":
        rect(draw, (px - 1, py - 5, px + 17, py + 15), "stone0")
        rect(draw, (px + 1, py - 3, px + 15, py + 13), "stone2")
        rect(draw, (px + 3, py, px + 13, py + 11), "shadow")
        for ax, ay in ((5, 6), (8, 3), (11, 7)):
            rect(draw, (px + ax, py + ay, px + ax + 1, py + 10), "amber1")
            rect(draw, (px + ax, py + ay + 2, px + ax, py + 9), "amber3")
        line(draw, (px + 1, py + 14, px + 16, py + 14), "stone4")
    elif glyph == "P":
        draw.ellipse((px + 2, py + 9, px + 16, py + 16), fill=color("shadow"))
        rect(draw, (px + 3, py - 3, px + 12, py + 12), "stone1")
        rect(draw, (px + 5, py - 3, px + 10, py + 10), "stone3")
        line(draw, (px + 5, py - 3, px + 10, py - 3), "stone5")
        rect(draw, (px + 2, py + 11, px + 13, py + 13), "stone2")
        if key == "hall" and (x, y) != (16, 10):
            rect(draw, (px + 6, py - 6, px + 9, py - 3), "stone4")
            draw.polygon(((px + 5, py - 2), (px + 10, py - 2), (px + 11, py + 6), (px + 4, py + 6)), fill=color("stone2"))
    elif glyph == "Q":
        rect(draw, (px + 2, py + 7, px + 14, py + 13), "shadow")
        rect(draw, (px + 3, py + 1, px + 12, py + 10), "stone2")
        rect(draw, (px + 4, py, px + 11, py + 2), "stone4")
        rect(draw, (px + 4, py + 7, px + 11, py + 9), "stone3")
        line(draw, (px + 4, py + 2, px + 4, py + 7), "stone4")
        if key == "wayhouse":
            rect(draw, (px + 1, py - 5, px + 14, py - 1), "teal0")
            line(draw, (px + 2, py - 4, px + 13, py - 4), "teal2")
        elif key == "hall" and x == 10:
            # The eighth body is scraped faceless; no crown remains.
            rect(draw, (px + 6, py - 8, px + 10, py - 5), "stone1")
            rect(draw, (px + 4, py - 4, px + 12, py + 4), "stone2")
            line(draw, (px + 5, py - 3, px + 9, py - 1), "stone0")
            line(draw, (px + 6, py + 1, px + 11, py + 3), "stone0")
    elif glyph == "M":
        rect(draw, (px, py, px + 15, py + 15), "stone2")
        line(draw, (px + 2, py + 13, px + 7, py + 6, px + 13, py + 3), "silver")
        line(draw, (px + 3, py + 3, px + 7, py + 6, px + 12, py + 12), "teal2")
        rect(draw, (px + 11, py + 3, px + 13, py + 5), "bone")
    elif glyph == "D":
        rect(draw, (px, py - 1, px + 15, py + 15), "shadow")
        for index in range(5):
            yy = py + index * 3
            line(draw, (px + index // 2, yy, px + 15 - index // 2, yy), "stone3")
            line(draw, (px + index // 2, yy + 1, px + 15 - index // 2, yy + 1), "stone1")
    elif glyph == "+":
        if key == "pony" or key == "bree" and (x, y) != (10, 1):
            rect(draw, (px + 3, py - 3, px + 12, py + 12), "wood0")
            rect(draw, (px + 4, py - 2, px + 11, py + 9), "wood2")
            for ax in (5, 8, 11):
                line(draw, (px + ax, py - 1, px + ax, py + 9), "wood1")
            draw.point((px + 10, py + 4), fill=color("amber2"))
            line(draw, (px + 3, py + 12, px + 12, py + 12), "wood4")
        else:
            line(draw, (px, py + 1, px + 15, py + 1), "stone3")


def _decorations(image: Image.Image, key: str) -> None:
    draw = ImageDraw.Draw(image)
    spec = WORLD_MAPS[key]
    for x, y in spec.lights if key != "lantern" else ():
        px, py = x * TILE + 8, y * TILE + 5
        rect(draw, (px - 2, py + 2, px + 2, py + 6), "wood0")
        rect(draw, (px - 1, py, px + 1, py + 3), "amber2")
        draw.point((px, py - 1), fill=color("amber3"))
        line(draw, (px - 3, py + 6, px + 3, py + 6), "wood4")
    if key == "pony":
        # Windows glow through blue-green leaded glass along the north wall.
        for px in (40, 104, 168):
            rect(draw, (px, 19, px + 11, 30), "wood0")
            rect(draw, (px + 1, 20, px + 10, 28), "teal0")
            line(draw, (px + 2, 21, px + 8, 27), "teal1")
            line(draw, (px + 8, 21, px + 2, 27), "teal1")
            line(draw, (px + 5, 20, px + 5, 28), "wood3")
        # Benches and the overturned stool make the encounter feel lived in.
        for x, y in ((4, 5), (8, 5), (10, 7), (14, 8), (4, 11)):
            px, py = x * TILE + 5, y * TILE + 4
            rect(draw, (px, py + 2, px + 5, py + 5), "wood0")
            line(draw, (px, py + 1, px + 5, py + 1), "wood3")
        line(draw, (147, 136, 154, 142), "wood4")
        line(draw, (150, 134, 157, 140), "wood2")
        rect(draw, (146, 135, 153, 137), "wood3")
        # A dark red broken-arrow trace beside the fallen messenger.
        line(draw, (46, 57, 52, 60), "blood")
        line(draw, (49, 55, 56, 52), "wood0")
        # Braces, wall barrels, a patched runner, and a rack of hanging mugs.
        for xx in (28, 92, 156, 220, 284):
            line(draw, (xx, 19, xx + 7, 29), "wood0")
            line(draw, (xx + 1, 19, xx + 8, 29), "wood3")
        rect(draw, (136, 133, 175, 173), "wood0")
        rect(draw, (138, 135, 173, 171), "purple0")
        for yy in (138, 168):
            line(draw, (140, yy, 171, yy), "amber0")
        for yy in range(141, 166, 6):
            line(draw, (145, yy, 148, yy + 2, 145, yy + 4), "purple1")
            line(draw, (166, yy, 163, yy + 2, 166, yy + 4), "purple1")
        line(draw, (145, 154, 149, 154), "wood3")
        for xx in range(236, 276, 6):
            rect(draw, (xx, 26, xx + 2, 29), "stone4")
            draw.point((xx + 3, 27), fill=color("bone"))
    elif key == "bree":
        _bree_buildings(draw)
        # Inn hanging horse sign, stable fence, hedge, and barred north gate.
        line(draw, (199, 96, 209, 96), "wood3")
        rect(draw, (200, 97, 208, 106), "wood0")
        line(draw, (203, 100, 206, 100, 207, 98), "bone")
        line(draw, (202, 102, 206, 102), "bone")
        for xx in range(33, 97, 8):
            rect(draw, (xx, 132, xx + 1, 143), "wood3")
            draw.point((xx, 131), fill=color("wood4"))
        line(draw, (33, 136, 98, 136), "wood2")
        line(draw, (33, 140, 98, 140), "wood2")
        for xx in (151, 183):
            rect(draw, (xx, 13, xx + 2, 28), "wood0")
            line(draw, (xx, 13, xx + 2, 13), "wood4")
        line(draw, (153, 19, 182, 19), "wood2")
        line(draw, (153, 24, 182, 24), "wood2")
        for xx in range(158, 180, 5):
            line(draw, (xx, 14, xx, 26), "wood3")
        # Roof ridges, masonry chimneys, and mossy eaves establish buildings
        # rather than flat rectangles of repeating roof tiles.
        for xx in range(194, 299, 4):
            line(draw, (xx, 72, xx + 2, 72), "roof3")
        line(draw, (194, 73, 299, 73), "roof0")
        for xx, yy in ((246, 39), (62, 38)):
            rect(draw, (xx - 1, yy + 2, xx + 11, yy + 10), "shadow")
            rect(draw, (xx, yy - 4, xx + 9, yy + 6), "stone1")
            for row in range(yy - 4, yy + 7, 3):
                line(draw, (xx, row, xx + 9, row), "stone3")
            rect(draw, (xx - 1, yy - 5, xx + 10, yy - 3), "stone4")
            rect(draw, (xx + 2, yy - 5, xx + 7, yy - 4), "shadow")
        # Wet wagon wheel and stacks of hay beside the stable.
        draw.ellipse((113, 167, 123, 177), outline=color("wood3"))
        line(draw, (118, 168, 118, 176), "wood2")
        line(draw, (114, 172, 122, 172), "wood2")
        for xx, yy in ((37, 202), (47, 205)):
            rect(draw, (xx, yy, xx + 9, yy + 5), "straw0")
            for offset in (1, 3):
                line(draw, (xx, yy + offset, xx + 9, yy + offset), "straw1")
            line(draw, (xx + 4, yy, xx + 4, yy + 5), "wood0")
    elif key == "wayhouse":
        # Rusted bronze weapon hooks around the flooded armory.
        for xx in (23, 39, 55, 71):
            line(draw, (xx, 30, xx, 36, xx + 3, 36), "amber0")
        # A split-crown motif beside the sealed stair.
        line(draw, (156, 161, 159, 157, 162, 161, 165, 157, 169, 162), "bone")
        line(draw, (156, 163, 168, 163), "stone4")
        line(draw, (162, 158, 164, 165), "stone0")
        # The archive mosaic is a single floor map: bright northern roads,
        # one later black route, and the crown split into eight fragments.
        rect(draw, (144, 32, 175, 63), "stone3")
        rect(draw, (146, 34, 173, 61), "stone1")
        for yy in range(35, 62, 3):
            for xx in range(147, 174, 3):
                draw.point((xx, yy), fill=color("stone2"))
        for points in ((148, 38, 159, 46, 169, 37), (150, 55, 159, 46, 171, 55), (159, 35, 159, 46)):
            line(draw, points, "silver")
        line(draw, (159, 46, 160, 55, 164, 58), "shadow")
        for xx in (149, 159, 169):
            draw.point((xx, 38), fill=color("bone"))
        line(draw, (162, 57, 163, 55, 165, 57, 168, 55, 170, 58), "amber1")
        line(draw, (163, 59, 169, 59), "amber0")
        draw.point((166, 57), fill=color("shadow"))
        # Fallen stone lintels and roots suggest a buried, ruined fortress.
        for xx, yy in ((45, 157), (257, 179), (113, 195)):
            rect(draw, (xx + 1, yy + 2, xx + 17, yy + 7), "shadow")
            rect(draw, (xx, yy, xx + 15, yy + 4), "stone2")
            line(draw, (xx, yy, xx + 14, yy), "stone4")
            line(draw, (xx + 7, yy, xx + 8, yy + 4), "stone0")
        line(draw, (31, 31, 35, 38, 33, 42), "wood2")
        line(draw, (38, 31, 35, 38, 39, 46), "wood1")
    elif key == "hall":
        # Columns of memorial names, rendered as deliberate ancient marks.
        for column in range(8):
            px = 23 + column * 35
            for row in range(3):
                py = 31 + row * 3
                line(draw, (px, py, px + 2 + (column + row) % 3, py), "stone4")
                draw.point((px + 6, py), fill=color("amber0"))
        # An eight-spoked floor medallion, worn by returning travelers.
        cx, cy = 165, 120
        draw.ellipse((cx - 19, cy - 19, cx + 19, cy + 19), outline=color("stone3"))
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), outline=color("stone0"))
        for dx, dy in ((0, -16), (0, 16), (-16, 0), (16, 0), (-11, -11), (11, 11), (-11, 11), (11, -11)):
            line(draw, (cx, cy, cx + dx, cy + dy), "stone3")
        rect(draw, (cx - 2, cy - 2, cx + 2, cy + 2), "stone4")
    elif key == "lantern":
        # The one ordinary lantern hangs from a patched dark iron bracket.
        px, py = 216, 86
        line(draw, (px, py - 9, px, py - 3), "stone4")
        rect(draw, (px - 3, py - 2, px + 3, py + 6), "wood0")
        rect(draw, (px - 2, py - 1, px + 2, py + 4), "amber2")
        line(draw, (px, py - 1, px, py + 4), "wood0")
        line(draw, (px - 3, py + 6, px + 3, py + 6), "stone4")
        line(draw, (149, 53, 170, 53), "stone0")
        line(draw, (151, 55, 168, 55), "stone0")
        # The low arch is uneven masonry; its east side has been repaired.
        for xx in range(30, 290, 19):
            yy = 62 if xx < 131 or xx > 189 else 42
            rect(draw, (xx, yy, xx + 11, yy + 3), "stone2")
            line(draw, (xx, yy, xx + 11, yy), "stone3")
        # A bedroll beside the optional recovery point adds no new reward.
        rect(draw, (211, 166, 228, 174), "shadow")
        rect(draw, (210, 165, 226, 171), "teal0")
        line(draw, (211, 165, 224, 165), "teal1")
        rect(draw, (210, 164, 214, 172), "cloth1")


def generate_map(key: str) -> Image.Image:
    spec = WORLD_MAPS[key]
    image = Image.new("RGB", WORLD_SIZE, color("void"))
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(spec.grid):
        for x, glyph in enumerate(row):
            rng = random.Random(f"roads-world-{key}-{x}-{y}")
            _floor(draw, x, y, glyph, key, rng)
    # Props are painted north to south, with feet anchored to collision tiles.
    for y, row in enumerate(spec.grid):
        for x, glyph in enumerate(row):
            if glyph not in ".,=:":
                _prop(draw, x, y, glyph, key, spec.grid, random.Random(f"prop-{key}-{x}-{y}"))
    _decorations(image, key)
    return image


def _human(image: Image.Image, name: str, direction: int, frame: int, offset: tuple[int, int]) -> None:
    draw = ImageDraw.Draw(image)
    ox, oy = offset
    bob = 1 if frame == 2 else 0
    leg = (-1, 0, 1, 0)[frame]
    # Deliberate silhouette differences, even at native size.
    coats = {
        "traveler": ("teal0", "teal1", "teal2"),
        "mara": ("purple0", "purple1", "cloth2"),
        "tobin": ("wood2", "wood3", "amber0"),
        "calenor": ("grass0", "grass2", "moss"),
        "orc": ("cloth0", "cloth1", "stone3"),
        "orc_scout": ("wood0", "wood2", "wood3"),
        "patron": ("cloth0", "cloth1", "cloth2"),
        "butterbur": ("wood1", "wood2", "wood3"),
    }
    dark, middle, light = coats[name]
    def r(box: tuple[int, int, int, int], shade: str) -> None:
        x1, y1, x2, y2 = box
        rect(draw, (ox + x1, oy + y1 + bob, ox + x2, oy + y2 + bob), shade)
    def l(points: tuple[int, ...], shade: str) -> None:
        translated = tuple(value + (ox if index % 2 == 0 else oy + bob) for index, value in enumerate(points))
        line(draw, translated, shade)
    r((7 + leg, 19, 9 + leg, 21), "shadow")
    r((11 - leg, 19, 13 - leg, 21), "shadow")
    r((7 + leg, 19, 8 + leg, 19), "wood3")
    r((11 - leg, 19, 12 - leg, 19), "wood3")
    draw.polygon([(ox + 6, oy + 9 + bob), (ox + 13, oy + 9 + bob), (ox + 15, oy + 18 + bob), (ox + 5, oy + 18 + bob)], fill=color(dark))
    r((8, 10, 11, 18), middle)
    l((6, 10, 5, 17), light)
    r((6, 13, 14, 14), "wood0")
    r((10, 13, 11, 14), "amber1")
    r((7, 5, 12, 9), "grass3" if name in {"orc", "orc_scout"} else "skin1")
    r((8, 6, 12, 8), "moss" if name in {"orc", "orc_scout"} else "skin2")
    r((7, 3, 12, 5), "wood0" if name != "calenor" else "stone3")
    r((6, 5, 7, 8), "wood0" if name != "calenor" else "stone4")
    if direction == 3:
        r((7, 5, 12, 8), "wood0")
        r((8, 5, 11, 7), "wood1")
        r((6, 9, 13, 10), light)
        r((8, 11, 11, 15), dark)
    elif direction == 1:
        r((6, 6, 8, 8), "skin2")
        r((6, 6, 6, 6), "shadow")
        r((11, 5, 13, 8), "wood0")
        r((6, 10, 9, 17), middle)
    elif direction == 2:
        r((11, 6, 13, 8), "skin2")
        r((13, 6, 13, 6), "shadow")
        r((6, 5, 8, 8), "wood0")
        r((10, 10, 13, 17), middle)
    else:
        r((8, 7, 8, 7), "shadow")
        r((11, 7, 11, 7), "shadow")
        r((9, 9, 10, 9), "skin0")
    if name == "traveler":
        # A visible satchel, silver-star glint and the old traveler's cloak.
        r((12, 14, 15, 17), "wood2")
        l((7, 10, 13, 15), "wood3")
        r((10, 11, 10, 11), "silver")
    elif name == "mara":
        r((13, 5, 14, 10), "wood0")
        l((4, 13, 3, 18), "silver")
        l((15, 13, 16, 17), "silver")
        r((7, 3, 13, 4), "wood0")
    elif name == "tobin":
        r((6, 3, 13, 5), "stone0")
        l((6, 3, 12, 3), "stone4")
        l((15, 10, 15, 19), "wood3")
        r((14, 13, 17, 17), "wood0")
        r((15, 14, 16, 16), "amber2")
    elif name == "calenor":
        r((8, 8, 11, 10), "stone4")
        l((4, 11, 4, 21), "wood4")
        r((11, 10, 12, 17), "grass1")
    elif name == "orc":
        r((5, 5, 6, 7), "moss")
        r((13, 5, 15, 7), "moss")
        r((7, 3, 12, 4), "cloth0")
        r((7, 9, 13, 11), "stone2")
        r((10, 10, 12, 11), "blood")
        r((3, 12, 4, 20), "wood3")
        r((1, 11, 4, 14), "stone3")
        l((1, 11, 4, 11), "silver")
    elif name == "orc_scout":
        r((5, 5, 6, 7), "grass3")
        r((13, 5, 14, 7), "grass3")
        l((4, 12, 3, 18), "silver")
        r((8, 10, 10, 13), "cloth0")
    elif name == "butterbur":
        r((5, 10, 14, 18), "wood2")
        r((7, 11, 12, 17), "bone")
        r((8, 12, 11, 16), "stone5")
        r((5, 12, 6, 15), "skin1")
        r((13, 12, 14, 15), "skin1")
        r((8, 8, 11, 9), "wood0")
    elif name == "patron":
        r((6, 3, 13, 5), "wood2")
        l((5, 5, 14, 5), "wood3")
        r((9, 8, 11, 10), "wood1")


def _edrin(image: Image.Image, offset: tuple[int, int]) -> None:
    draw = ImageDraw.Draw(image)
    x, y = offset
    rect(draw, (x + 3, y + 15, x + 16, y + 20), "cloth0")
    rect(draw, (x + 4, y + 16, x + 10, y + 19), "teal0")
    rect(draw, (x + 2, y + 15, x + 5, y + 18), "skin1")
    rect(draw, (x + 1, y + 14, x + 4, y + 15), "wood0")
    rect(draw, (x + 12, y + 18, x + 17, y + 20), "shadow")
    line(draw, (x + 8, y + 16, x + 10, y + 18), "blood")
    line(draw, (x + 9, y + 16, x + 14, y + 12), "wood0")
    draw.point((x + 8, y + 17), fill=color("silver"))


def generate_characters() -> Image.Image:
    atlas = Image.new("RGBA", (80, 288), (0, 0, 0, 0))
    for direction in range(4):
        for frame in range(4):
            _human(atlas, "traveler", direction, frame, (frame * 20, direction * 24))
    for row, name in enumerate(("mara", "tobin", "calenor", "edrin", "orc", "orc_scout", "patron", "butterbur"), 4):
        for frame in range(4):
            if name == "edrin":
                _edrin(atlas, (frame * 20, row * 24))
            else:
                # Idle characters breathe, but never march in place.
                _human(atlas, name, 0, 2 if frame == 2 else 0, (frame * 20, row * 24))
    return atlas


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for key in WORLD_MAPS:
        generate_map(key).save(DESTINATION / f"world-{key}.png", optimize=True)
    generate_characters().save(DESTINATION / "world-characters.png", optimize=True)
    print("Generated five 320x240 worlds and a four-direction animated character atlas.")


if __name__ == "__main__":
    main()
