"""Shared desktop typography with the same metrics on every platform.

SDL stays owned by the window: importing this module does not import pygame
or open a display. The bundled, unmodified DejaVu fonts retain their license.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


FONT_DIRECTORY = Path(__file__).resolve().parent / "font_assets"
FONT_FILES = ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "LICENSE.txt")

# Warm ink and quiet metals belong to the road, rather than a desktop widget.
# Text colors stay bright enough to read on either of the charcoal surfaces.
INK = (16, 21, 27)
PANEL = (23, 31, 38)
CARD = (29, 39, 46)
SELECTED = (40, 51, 52)
EDGE = (65, 78, 79)
PARCHMENT = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 156, 151)
MUTED = (159, 161, 150)
RED = (219, 132, 113)
STEEL = (177, 193, 189)
SHADOW = (9, 15, 20)

ORIGIN_PORTRAIT_FILE = Path(__file__).resolve().parent / "pixel_assets" / "world-origin-portraits.png"
ORIGIN_PORTRAIT_SIZE = (64, 80)


def origin_face_rect(origin: str) -> tuple[int, int, int, int] | None:
    """Locate the optional portrait without changing the playable sprite atlas."""
    index = {
        "bree_wayfarer": 0, "wayfarer": 0,
        "north_road_scout": 1, "scout": 1,
        "healers_apprentice": 2, "healer": 2,
    }.get(origin)
    return (index * 64, 0, 64, 80) if index is not None else None


def draw_pixel_frame(pg: Any, screen: Any, rect: Any, *, fill: Any = PANEL,
                     edge: Any = EDGE, accent: Any = None, ornate: bool = False) -> None:
    """Draw an integer-pixel frame; its metalwork stays inside the given bounds."""
    rect = pg.Rect(rect)
    if rect.width < 2 or rect.height < 2:
        return
    pg.draw.rect(screen, fill, rect)
    pg.draw.rect(screen, edge, rect, 1)
    if rect.width > 8 and rect.height > 8:
        pg.draw.line(screen, SHADOW, (rect.left + 2, rect.bottom - 2), (rect.right - 3, rect.bottom - 2))
        pg.draw.line(screen, SHADOW, (rect.right - 2, rect.top + 2), (rect.right - 2, rect.bottom - 3))
    if not ornate or min(rect.width, rect.height) < 32:
        return
    accent = accent or AMBER
    for x, y, dx, dy in ((rect.left + 3, rect.top + 3, 1, 1),
                          (rect.right - 4, rect.top + 3, -1, 1),
                          (rect.left + 3, rect.bottom - 4, 1, -1),
                          (rect.right - 4, rect.bottom - 4, -1, -1)):
        pg.draw.line(screen, accent, (x, y), (x + dx * 13, y))
        pg.draw.line(screen, accent, (x, y), (x, y + dy * 13))
        pg.draw.line(screen, edge, (x + dx * 3, y + dy * 3), (x + dx * 9, y + dy * 3))
        pg.draw.line(screen, edge, (x + dx * 3, y + dy * 3), (x + dx * 3, y + dy * 9))
        pg.draw.rect(screen, accent, (min(x + dx * 6, x + dx * 8), min(y + dy * 6, y + dy * 8), 2, 2))


def draw_medallion(pg: Any, screen: Any, center: tuple[int, int], *, radius: int = 14,
                  accent: Any = AMBER) -> None:
    """A small eight-point road mark, cut as pixels rather than a smooth seal."""
    x, y = center
    radius = max(6, int(radius))
    shoulder = max(3, radius // 2)
    points = [(x - shoulder, y - radius), (x + shoulder, y - radius),
              (x + radius, y - shoulder), (x + radius, y + shoulder),
              (x + shoulder, y + radius), (x - shoulder, y + radius),
              (x - radius, y + shoulder), (x - radius, y - shoulder)]
    pg.draw.polygon(screen, INK, points)
    pg.draw.polygon(screen, EDGE, points, 1)
    ray = max(3, radius - 6)
    pg.draw.line(screen, accent, (x - ray, y), (x + ray, y))
    pg.draw.line(screen, accent, (x, y - ray), (x, y + ray))
    diagonal = max(2, ray - 3)
    pg.draw.line(screen, accent, (x - diagonal, y - diagonal), (x + diagonal, y + diagonal))
    pg.draw.line(screen, accent, (x - diagonal, y + diagonal), (x + diagonal, y - diagonal))
    pg.draw.rect(screen, PARCHMENT, (x - 1, y - 1, 3, 3))


def missing_font_assets() -> list[Path]:
    return [FONT_DIRECTORY / name for name in FONT_FILES if not (FONT_DIRECTORY / name).is_file()]


def load_font(pg: Any, size: int, *, bold: bool = False) -> Any:
    """Load readable, consistently measured text, with a damaged-install fallback."""
    filename = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return pg.font.Font(str(FONT_DIRECTORY / filename), max(1, int(size)))
    except (OSError, ValueError, pg.error):
        return pg.font.SysFont("dejavusansmono,courier,monospace", max(1, int(size)), bold=bold)


def initial_window_size(desktop: tuple[int, int], preferred: tuple[int, int] = (1200, 900)) -> tuple[int, int]:
    """Leave room for the desktop's title bar and dock on common laptop displays."""
    width, height = desktop
    if width <= 0 or height <= 0:
        return preferred
    available_width = max(760, width - 48)
    available_height = max(560, height - 80)
    return min(preferred[0], available_width), min(preferred[1], available_height)


def wrap_text(text: str, font: Any, width: int) -> list[str]:
    """Wrap measured text while preserving blank paragraphs and long words."""
    width = max(1, width)
    output: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            output.append("")
            continue
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if font.size(candidate)[0] <= width:
                line = candidate
                continue
            if line:
                output.append(line)
                line = ""
            while word and font.size(word)[0] > width:
                cut = 1
                while cut < len(word) and font.size(word[:cut + 1])[0] <= width:
                    cut += 1
                output.append(word[:cut])
                word = word[cut:]
            line = word
        if line:
            output.append(line)
    return output or [""]
