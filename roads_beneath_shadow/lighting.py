"""Terminal ink for converted art; characters and silhouettes stay untouched."""

from __future__ import annotations


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    SILVER = "\033[38;5;250m"


# Low-density converter marks recede; the solid subject catches the light.
# The same four inks drive terminal output and the development contact sheet.
ART_PALETTES: dict[str, tuple[int, int, int, int]] = {
    Color.SILVER: (103, 109, 152, 231),
    Color.YELLOW: (137, 173, 222, 230),
    Color.GREEN: (65, 108, 151, 230),
    Color.BLUE: (60, 67, 110, 189),
    Color.CYAN: (66, 73, 159, 231),
    Color.RED: (95, 131, 173, 224),
    Color.MAGENTA: (60, 97, 140, 189),
    Color.WHITE: (102, 145, 188, 231),
}
ASCII_RAMP = " .:-=+*#@"


def art_ink(character: str, color: str) -> int | None:
    """Return a palette index for a raw converter mark, or preserve its ink."""

    palette = ART_PALETTES.get(color)
    if palette is None or character not in ASCII_RAMP or character == " ":
        return None
    if character in ".:":
        return palette[0]
    if character in "-=+":
        return palette[1]
    if character in "*#":
        return palette[2]
    return palette[3]


def xterm_rgb(index: int) -> tuple[int, int, int]:
    """Resolve the standard 256-color cube for portable artwork previews."""

    if not 16 <= index <= 255:
        raise ValueError("art ink must use the 256-color cube or grayscale ramp")
    if index >= 232:
        gray = 8 + 10 * (index - 232)
        return gray, gray, gray
    red, remainder = divmod(index - 16, 36)
    green, blue = divmod(remainder, 6)
    levels = (0, 95, 135, 175, 215, 255)
    return levels[red], levels[green], levels[blue]
