"""Shared desktop typography with the same metrics on every platform.

SDL stays owned by the window: importing this module does not import pygame
or open a display. The bundled, unmodified DejaVu fonts retain their license.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


FONT_DIRECTORY = Path(__file__).resolve().parent / "font_assets"
FONT_FILES = ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "LICENSE.txt")


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
