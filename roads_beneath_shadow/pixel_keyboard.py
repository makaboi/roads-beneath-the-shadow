"""An optional controller and pointer keyboard for naming a traveler.

The window owns the real text editor and request.  This view only returns
small immutable edits, so opening or closing it cannot choose a story route.
Importing it does not initialize SDL or require a connected controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .pixel_theme import (
    AMBER, CARD, EDGE, INK, MUTED, PARCHMENT, SELECTED, TEAL,
    draw_pixel_frame, load_font, wrap_text,
)


@dataclass(frozen=True)
class KeyboardEdit:
    kind: str
    text: str = ""


_ROWS = (
    tuple("qwertyuiop"),
    tuple("asdfghjkl"),
    tuple("zxcvbnm"),
    tuple("1234567890"),
    ("case", "space", "delete", "done", "close"),
)


class NameKeyboard:
    """Render a keyboard whose edits go through the window's Unicode editor.

    Commands are ``up``, ``down``, ``left``, ``right``, ``confirm`` and
    ``back``.  ``back`` closes this view without cancelling character creation.
    The window retains responsibility for the editor's character limit and
    final name validation.  ``draw`` updates whether Done may be selected.
    """

    def __init__(self, pg: Any) -> None:
        self.pg = pg
        self.active = False
        self.uppercase = False
        self.row = 0
        self.column = 0
        self._column_intent = 0
        self._name_present = False
        self.hit_targets: list[tuple[Any, tuple[int, int]]] = []
        self._fallback_fonts: dict[int, Any] = {}

    def open(self) -> None:
        self.active = True
        self.uppercase = False
        self.row = self.column = self._column_intent = 0
        self._name_present = False
        self.hit_targets = []

    def close(self) -> None:
        self.active = False
        self.hit_targets = []

    @property
    def selected_key(self) -> str:
        return _ROWS[self.row][self.column]

    def command(self, command: str) -> KeyboardEdit | None:
        if not self.active:
            return None
        if command == "back":
            self.close()
            return KeyboardEdit("close")
        if command in {"up", "down"}:
            self.row = (self.row + (-1 if command == "up" else 1)) % len(_ROWS)
            self.column = min(self._column_intent, len(_ROWS[self.row]) - 1)
        elif command in {"left", "right"}:
            self.column = (self.column + (-1 if command == "left" else 1)) % len(_ROWS[self.row])
            self._column_intent = self.column
        elif command == "confirm":
            return self._activate()
        return None

    def _activate(self) -> KeyboardEdit | None:
        key = self.selected_key
        if key == "case":
            self.uppercase = not self.uppercase
        elif key == "space":
            return KeyboardEdit("insert", " ")
        elif key == "delete":
            return KeyboardEdit("backspace")
        elif key == "done":
            if self._name_present:
                return KeyboardEdit("confirm")
        elif key == "close":
            self.close()
            return KeyboardEdit("close")
        else:
            return KeyboardEdit("insert", key.upper() if self.uppercase else key)
        return None

    def handle_event(self, event: Any) -> tuple[bool, KeyboardEdit | None]:
        """Consume pointer events in the open modal without leaking a click."""
        if not self.active:
            return False, None
        pg = self.pg
        if event.type == pg.MOUSEBUTTONDOWN:
            if event.button == 1:
                for rect, (row, column) in self.hit_targets:
                    if rect.collidepoint(event.pos):
                        self.row, self.column = row, column
                        self._column_intent = column
                        return True, self._activate()
            return True, None
        if event.type == pg.MOUSEMOTION:
            hovered = next((position for rect, position in self.hit_targets if rect.collidepoint(event.pos)), None)
            if hovered is not None:
                self.row, self.column = hovered
                self._column_intent = self.column
            return True, None
        return event.type in {pg.MOUSEBUTTONUP, pg.MOUSEWHEEL}, None

    def _label(self, key: str) -> str:
        return {
            "case": "abc" if self.uppercase else "ABC",
            "space": "Space", "delete": "Delete", "done": "Done", "close": "Close",
        }.get(key, key.upper() if self.uppercase else key)

    def _button_text(self, screen: Any, rect: Any, label: str, font: Any, small_font: Any, color: Any) -> None:
        available = rect.inflate(-10, -8)
        selected_font = font if font.size(label)[0] <= available.width and font.get_height() <= available.height else small_font
        if selected_font.size(label)[0] > available.width or selected_font.get_height() > available.height:
            for size in range(min(18, selected_font.get_height()), 7, -1):
                if size not in self._fallback_fonts:
                    self._fallback_fonts[size] = load_font(self.pg, size)
                candidate = self._fallback_fonts[size]
                if candidate.size(label)[0] <= available.width and candidate.get_height() <= available.height:
                    selected_font = candidate
                    break
        glyph = selected_font.render(label, False, color)
        screen.blit(glyph, glyph.get_rect(center=rect.center))

    def draw(self, screen: Any, rect: Any, font: Any, small_font: Any, current_name: str) -> None:
        if not self.active:
            return
        pg = self.pg
        rect = pg.Rect(rect)
        self.hit_targets = []
        self._name_present = bool(current_name.strip())
        if rect.width < 260 or rect.height < 220:
            return
        old_clip = screen.get_clip()
        screen.set_clip(rect.clip(old_clip))
        draw_pixel_frame(pg, screen, rect, fill=INK, accent=AMBER, ornate=True)
        padding = 16 if rect.width >= 500 else 10
        left, width = rect.left + padding, rect.width - 2 * padding
        y = rect.top + padding
        compact = rect.height < 340
        heading_font = small_font if compact else font
        heading = "NAME YOUR TRAVELER"
        for line in wrap_text(heading, heading_font, width):
            screen.blit(heading_font.render(line, False, AMBER), (left, y))
            y += heading_font.get_linesize() + 2
        if not compact:
            note = "Choose letters, then Done. Physical typing also works."
            for line in wrap_text(note, small_font, width):
                screen.blit(small_font.render(line, False, MUTED), (left, y))
                y += small_font.get_linesize() + 2
        name_font = small_font if compact else font
        name_rect = pg.Rect(left, y + (4 if compact else 8), width,
                            max(24, name_font.get_linesize() + 8) if compact else max(34, font.get_linesize() + 14))
        draw_pixel_frame(pg, screen, name_rect, fill=CARD, edge=TEAL)
        shown = current_name or "Your name"
        while len(shown) > 1 and name_font.size(shown)[0] > name_rect.width - 20:
            shown = "…" + shown[2:] if shown.startswith("…") else "…" + shown[1:]
        screen.blit(name_font.render(shown, False, PARCHMENT if current_name else MUTED),
                    (name_rect.left + 10, name_rect.top + (4 if compact else 7)))
        y = name_rect.bottom + (6 if compact else 12)
        hint = "A: choose  B: close" if compact else "Arrows / D-pad: move  ·  A / Enter: choose  ·  B / Esc: close"
        hint_lines = wrap_text(hint, small_font, width)
        footer_height = len(hint_lines) * (small_font.get_linesize() + 2) + 8
        bottom = rect.bottom - padding - footer_height
        gap = 4 if compact else 5
        row_height = max(1, (bottom - y - gap * (len(_ROWS) - 1)) // len(_ROWS))
        for row_index, keys in enumerate(_ROWS):
            # Alphabet and number rows keep a common key width; shorter rows
            # are centered rather than stretching their letters into slabs.
            columns = 10 if row_index < 4 else len(keys)
            key_width = (width - gap * (columns - 1)) // columns
            row_width = len(keys) * key_width + gap * (len(keys) - 1)
            x = left + (width - row_width) // 2
            for column_index, key in enumerate(keys):
                tile = pg.Rect(x + column_index * (key_width + gap), y + row_index * (row_height + gap), key_width, row_height)
                selected = (row_index, column_index) == (self.row, self.column)
                enabled = key != "done" or self._name_present
                draw_pixel_frame(pg, screen, tile, fill=SELECTED if selected else CARD,
                                 edge=AMBER if selected else EDGE)
                self._button_text(screen, tile, self._label(key), font, small_font,
                                  AMBER if selected and enabled else PARCHMENT if enabled else MUTED)
                self.hit_targets.append((tile, (row_index, column_index)))
        footer_y = bottom + 8
        for line in hint_lines:
            screen.blit(small_font.render(line, False, MUTED), (left, footer_y))
            footer_y += small_font.get_linesize() + 2
        screen.set_clip(old_clip)
