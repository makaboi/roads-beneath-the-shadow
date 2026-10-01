"""Generate deterministic retro marketing art for the GitHub repository."""

from __future__ import annotations

import math
import random
import sys
import textwrap
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "assets"
FONT_PATHS = (
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "DejaVuSansMono.ttf",
)
sys.path.insert(0, str(ROOT))

from roads_beneath_shadow import artwork, journey_artwork, part_two_artwork  # noqa: E402
from roads_beneath_shadow.lighting import ASCII_RAMP, Color, art_ink, xterm_rgb  # noqa: E402

INK = "#d7ded8"
MUTED = "#819188"
GREEN = "#80c98f"
GOLD = "#d5ad58"
RED = "#d46f6f"
SILVER = "#b9c8d1"
TERMINAL = "#0b1013"
PANEL = "#11191d"


@lru_cache(maxsize=12)
def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    raise RuntimeError("Preview generation needs Menlo, DejaVu Sans Mono, Liberation Mono, or Consolas.")


def draw_art_row(draw, position, text: str, face, color: str) -> None:
    """Use the game's inks and unchanged glyphs in exported terminal scenes."""

    palette_color = {SILVER: Color.SILVER, GOLD: Color.YELLOW, RED: Color.RED, GREEN: Color.GREEN}.get(color)
    if palette_color is None or any(character not in ASCII_RAMP for character in text):
        draw.text(position, text, font=face, fill=color)
        return
    x, y = position
    advance = face.getlength("M")
    for column, character in enumerate(text):
        ink = art_ink(character, palette_color)
        fill = xterm_rgb(ink) if ink is not None else color
        draw.text((x + column * advance, y), character, font=face, fill=fill)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, face, fill: str, width: int) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=face, fill=fill)


def add_scanlines(image: Image.Image, spacing: int = 5) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(0, image.height, spacing):
        draw.line((0, y, image.width, y), fill=(0, 0, 0, 24), width=1)


def star_points(cx: float, cy: float, outer: float, inner: float) -> list[tuple[float, float]]:
    points = []
    for index in range(16):
        angle = -math.pi / 2 + index * math.pi / 8
        radius = outer if index % 2 == 0 else inner
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points


def social_preview() -> Image.Image:
    width, height = 1280, 640
    image = Image.new("RGB", (width, height), "#080c0f")
    draw = ImageDraw.Draw(image, "RGBA")
    rng = random.Random(1937)

    for _ in range(220):
        x = rng.randrange(width)
        y = rng.randrange(height)
        alpha = rng.randrange(18, 65)
        draw.point((x, y), fill=(181, 199, 189, alpha))

    draw.rectangle((24, 24, width - 25, height - 25), outline=GOLD, width=3)
    draw.rectangle((36, 36, width - 37, height - 37), outline="#304239", width=1)
    draw.line((105, 103, width - 105, 103), fill="#42564b", width=2)
    draw.line((105, 500, width - 105, 500), fill="#42564b", width=2)

    draw.polygon(star_points(640, 156, 42, 14), fill=SILVER, outline="#f0f4f2")
    centered(draw, "A RETRO TERMINAL RPG", 60, font(23), GREEN, width)
    centered(draw, "ROADS", 220, font(92), INK, width)
    centered(draw, "BENEATH THE SHADOW", 326, font(54), GOLD, width)
    centered(draw, "CHOICES LEAVE MARKS.  THE ROAD REMEMBERS.", 422, font(24), SILVER, width)
    centered(draw, "PARTS I + II  //  THE ROAD REMEMBERS  //  PYTHON 3.10+", 538, font(21), MUTED, width)

    add_scanlines(image, 5)
    return image


def itch_cover() -> Image.Image:
    """Build itch.io's recommended 630x500 cover image."""
    width, height = 630, 500
    image = Image.new("RGB", (width, height), "#080c0f")
    draw = ImageDraw.Draw(image, "RGBA")
    rng = random.Random(1937)

    for _ in range(140):
        x = rng.randrange(width)
        y = rng.randrange(height)
        alpha = rng.randrange(18, 65)
        draw.point((x, y), fill=(181, 199, 189, alpha))

    draw.rectangle((16, 16, width - 17, height - 17), outline=GOLD, width=3)
    draw.rectangle((26, 26, width - 27, height - 27), outline="#304239", width=1)
    draw.polygon(star_points(width / 2, 104, 34, 11), fill=SILVER, outline="#f0f4f2")
    centered(draw, "A RETRO TERMINAL RPG", 48, font(18), GREEN, width)
    centered(draw, "ROADS", 160, font(70), INK, width)
    centered(draw, "BENEATH", 248, font(42), GOLD, width)
    centered(draw, "THE SHADOW", 302, font(42), GOLD, width)
    centered(draw, "THE ROAD REMEMBERS.", 390, font(18), SILVER, width)
    centered(draw, "PARTS I + II", 432, font(16), MUTED, width)
    add_scanlines(image, 5)
    return image


def art_rows(art: str, color: str) -> list[tuple[str, str]]:
    return [(line, color) for line in textwrap.dedent(art).strip("\n").splitlines()]


SCENES = [
    (title, art_rows(str(art), color) + [("", MUTED), (caption, MUTED)])
    for art, title, color, caption in (
        (artwork.TITLE_ART_EXPANDED, "THE SILVER STAR", SILVER, "Choices leave marks. The road remembers."),
        (artwork.PRANCING_PONY_EXTERIOR_ART, "ARRIVAL AT THE INN", GOLD, "Calenor promised seven days. Three weeks have passed."),
        (artwork.ORC_ATTACK_ART, "ORCS AT THE DOOR", RED, "The silver star. Take its bearer alive."),
        (journey_artwork.MIDGEWATER_CAMP_ART, "A FIRE WITHOUT FLAME", GOLD, "For a little while, neither has to be useful to anyone."),
        (artwork.BLACK_RIDER_CLIFFHANGER_ART, "THE BLACK RIDER", SILVER, "There is only one road left: down."),
        (journey_artwork.LAST_LANTERN_ART, "THE LAST LANTERN", GOLD, "No ancient power keeps it alight; someone remembered to fill it."),
        (part_two_artwork.FINAL_SEAL_BATTLE_ART, "THE FINAL SEAL BATTLE", RED, "What you promise is yours too."),
        (part_two_artwork.FORNOST_MAP_CLIFFHANGER_ART, "BENEATH RUINED FORNOST", SILVER, "We guarded the road. The Shadow was waking the city."),
    )
]


def gameplay_frame(
    scene_index: int,
    reveal: float,
    cursor: bool,
) -> Image.Image:
    width, height = 960, 600
    image = Image.new("RGB", (width, height), "#070a0c")
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=13, fill=PANEL, outline="#3d4c45", width=2)
    draw.rectangle((21, 21, width - 21, 61), fill="#182126")
    for x, color in ((42, "#d46f6f"), (66, GOLD), (90, GREEN)):
        draw.ellipse((x - 6, 35, x + 6, 47), fill=color)
    draw.text((124, 31), "Roads Beneath the Shadow — Terminal", font=font(17), fill=MUTED)

    title, lines = SCENES[scene_index]
    draw.text((48, 79), title, font=font(21), fill=GOLD)
    draw.line((48, 111, width - 48, 111), fill="#34463c", width=1)

    visible = max(1, math.ceil(len(lines) * reveal))
    y = 132
    face = font(16)
    line_step = min(25, 396 // max(1, len(lines)))
    block_width = max(len(text) for text, _color in lines)
    x = (width - face.getlength("M") * block_width) / 2
    for text, color in lines[:visible]:
        draw_art_row(draw, (x, y), text, face, color)
        y += line_step

    if cursor:
        draw.rectangle((53, 548, 65, 570), fill=GREEN)
    else:
        draw.text((53, 544), ">", font=face, fill=MUTED)

    draw.text(
        (width - 135, 548),
        f"{scene_index + 1}/{len(SCENES)}",
        font=font(15),
        fill=MUTED,
    )
    add_scanlines(image, 4)
    return image


def gameplay_gif() -> tuple[list[Image.Image], list[int]]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for index in range(len(SCENES)):
        for reveal, cursor, duration in ((0.58, False, 520), (1.0, True, 620), (1.0, False, 1500)):
            frame = gameplay_frame(index, reveal, cursor)
            frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=96))
            durations.append(duration)
    durations[-1] = 2600
    return frames, durations


def contact_sheet() -> Image.Image:
    sheet = Image.new("RGB", (1920, 600 * math.ceil(len(SCENES) / 2)), TERMINAL)
    for index in range(len(SCENES)):
        sheet.paste(gameplay_frame(index, 1.0, False), ((index % 2) * 960, (index // 2) * 600))
    return sheet


def animation_contact_sheet() -> Image.Image:
    """Show every existing animation frame with the new terminal lighting."""

    animations = (
        ("THE PRANCING PONY", artwork.PRANCING_PONY_EXTERIOR_ART, GOLD),
        ("THE REFORGED STAR", artwork.STAR_KEY_REFORGED_ART, SILVER),
        ("THE BLACK RIDER", artwork.BLACK_RIDER_CLIFFHANGER_ART, SILVER),
        ("THE WALL OF NAMES", part_two_artwork.WALL_NAMES_AWAKENING_ART, SILVER),
        ("THE FORNOST MAP", part_two_artwork.FORNOST_MAP_CLIFFHANGER_ART, GOLD),
    )
    sheet = Image.new("RGB", (1920, 500 * len(animations)), TERMINAL)
    face = font(18)
    for row, (title, animation, color) in enumerate(animations):
        for column, frame in enumerate(animation.frames):
            x = column * 960 + 70
            y = row * 500
            draw = ImageDraw.Draw(sheet)
            draw.text((x, y + 24), f"{title} — FRAME {column + 1}", font=font(21), fill=GOLD)
            for line_index, (line, ink) in enumerate(art_rows(frame, color)):
                draw_art_row(draw, (x, y + 68 + line_index * 20), line, face, ink)
    return sheet


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    social_preview().save(OUTPUT_DIR / "social-preview.png", optimize=True)
    itch_cover().save(OUTPUT_DIR / "itch-cover.png", optimize=True)
    contact_sheet().save(OUTPUT_DIR / "terminal-art-preview.png", optimize=True)
    animation_contact_sheet().save(OUTPUT_DIR / "animation-frames.png", optimize=True)

    frames, durations = gameplay_gif()
    frames[0].save(
        OUTPUT_DIR / "gameplay-demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    screenshot_dir = OUTPUT_DIR / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    for filename, scene_index in (
        ("story.png", 1),
        ("combat.png", 2),
        ("camp.png", 3),
        ("cliffhanger.png", 4),
        ("last-lantern.png", 5),
    ):
        gameplay_frame(scene_index, 1.0, False).save(
            screenshot_dir / filename,
            optimize=True,
        )

if __name__ == "__main__":
    main()
