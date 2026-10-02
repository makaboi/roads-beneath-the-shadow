"""A readable local archive that never answers a story request.

Original entries remain unchanged. Search and resize positions refer to source
characters, so wrapping cannot hide a found phrase or skip a remembered line.
Pygame is provided by the main-thread window; this module never initializes it.
"""

from __future__ import annotations

from array import array
from collections.abc import Sequence
from typing import Any
from unicodedata import combining, normalize

from .lighting import Color
from .pixel_theme import load_font, wrap_text


INK = (16, 21, 27)
PANEL = (23, 31, 38)
EDGE = (65, 78, 79)
PARCHMENT = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 156, 151)
MUTED = (159, 161, 150)
RED = (219, 132, 113)


def _normalized(text: str, *, folded: bool = False) -> tuple[str, list[tuple[int, int]]]:
    """Map collapsed whitespace and Unicode case folding to source spans."""
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        end = index + 1
        if text[index].isspace():
            while end < len(text) and text[end].isspace():
                end += 1
            characters.append(" ")
            spans.append((index, end))
        else:
            while end < len(text) and combining(text[end]):
                end += 1
            cluster = normalize("NFC", text[index:end])
            for character in cluster.casefold() if folded else cluster:
                characters.append(character)
                spans.append((index, end))
        index = end
    return "".join(characters), spans


class TranscriptView:
    """Copied archive with local search, source anchors, and explicit return.

    ``open(entries, scroll=None)`` preserves the reading position and query,
    while leaving search input inactive. ``close()`` releases text input; the
    window may then restore its pending name-entry field. ``handle_event``
    returns True only when the reader asks to close, never a game action.
    ``scroll`` counts lines backwards from the newest visible line.
    """

    def __init__(self, pg: Any) -> None:
        self.pg = pg
        self.entries: tuple[tuple[str, Any, bool], ...] = ()
        self.scroll = 0
        self.maximum_scroll = 0
        self.rows = 1
        self.query = ""
        self.searching = False
        self._query_selected = False
        self._composition = ""
        self.matches: list[int] = []
        self.match_index = 0
        self._match_positions: list[tuple[int, int, int]] = []
        self._match_pinned = False
        self._search_sources: list[tuple[str, array, array]] = []
        self._search_texts: tuple[str, ...] = ()
        self._search_version = -1
        self._lines: list[tuple[str, Any, bool, int]] = []
        self._line_spans: list[tuple[int, int]] = []
        self._entry_starts: dict[int, int] = {}
        self._version = 0
        self._layout_key: Any = None
        self._viewport_key: Any = None
        self._pending_anchor: tuple[int, int] | None = None
        self._pending_scroll: int | None = None
        self._font_size = 0
        self._content = pg.Rect(0, 0, 0, 0)
        self._search_field = pg.Rect(0, 0, 0, 0)
        self._scrollbar = pg.Rect(0, 0, 0, 0)
        self._thumb = pg.Rect(0, 0, 0, 0)
        self._dragging: int | None = None
        self._hits: list[tuple[Any, str]] = []
        self._fonts(17)

    def _fonts(self, size: int) -> None:
        if size == self._font_size:
            return
        self._font_size = size
        self.font = load_font(self.pg, size)
        self.bold_font = load_font(self.pg, size, bold=True)
        self.small_font = load_font(self.pg, max(13, size - 3))
        self.title_font = load_font(self.pg, size + 7, bold=True)
        self.line_height = self.font.get_linesize() + 4
        self._layout_key = None

    @property
    def reading_anchor(self) -> tuple[int, int] | None:
        """The source entry and character at the top of the reading column."""
        if not self._lines:
            return None
        line = max(0, len(self._lines) - self.scroll - self.rows)
        return self._lines[line][3], self._line_spans[line][0]

    def set_entries(self, entries: Sequence[tuple[str, Any, bool]]) -> None:
        copied = tuple((str(text), color, bool(bold)) for text, color, bold in entries)
        if copied == self.entries:
            return
        if self.scroll and self._pending_anchor is None:
            self._pending_anchor = self.reading_anchor
        self.entries = copied
        self._version += 1
        self._layout_key = None
        self._find_matches()

    def open(self, entries: Sequence[tuple[str, Any, bool]], *, scroll: int | None = None) -> None:
        self.set_entries(entries)
        if scroll is not None:
            self._pending_scroll = self.scroll = max(0, int(scroll))
            self._pending_anchor = None
            self._match_pinned = False
        self.close()

    def close(self) -> None:
        self.searching = False
        self._query_selected = False
        self._composition = ""
        self._dragging = None
        self.pg.key.stop_text_input()

    def _start_search(self, *, select: bool = True) -> None:
        self.searching = True
        self._query_selected = bool(self.query) and select
        self._composition = ""
        self.pg.key.start_text_input()
        if self._search_field.width:
            self.pg.key.set_text_input_rect(self._search_field)

    def _find_matches(self) -> None:
        previous = self._match_positions[self.match_index] if self._match_positions else None
        needle = _normalized(self.query, folded=True)[0].strip()
        positions = []
        if needle:
            if self._search_version != self._version:
                sources = []
                texts = tuple(text for text, _, _ in self.entries)
                for entry, text in enumerate(texts):
                    if entry < len(self._search_texts) and text == self._search_texts[entry]:
                        sources.append(self._search_sources[entry])
                    else:
                        folded, spans = _normalized(text, folded=True)
                        # Compact indices keep a long archive searchable without
                        # retaining a Python tuple for every source character.
                        sources.append((folded, array("I", (start for start, _ in spans)), array("I", (end for _, end in spans))))
                self._search_sources = sources
                self._search_texts = texts
                self._search_version = self._version
            for entry, (haystack, starts, ends) in enumerate(self._search_sources):
                cursor = 0
                while (found := haystack.find(needle, cursor)) >= 0:
                    positions.append((entry, starts[found], ends[found + len(needle) - 1]))
                    cursor = found + len(needle)
        self._match_positions = positions
        self.matches = [entry for entry, _, _ in positions]
        self.match_index = positions.index(previous) if previous in positions else min(self.match_index, max(0, len(positions) - 1))
        if not positions:
            self._match_pinned = False

    def _show_match(self) -> None:
        if not self._match_positions:
            return
        self._match_pinned = True
        if not self._lines:
            return
        entry, begin, end = self._match_positions[self.match_index]
        line = next((index for index, (_, _, _, source) in enumerate(self._lines) if source == entry and self._line_spans[index][1] > begin and self._line_spans[index][0] < end), self._entry_starts.get(entry, 0))
        self.scroll = max(0, min(self.maximum_scroll, self.maximum_scroll - line + 2))

    def _next_match(self, direction: int = 1) -> None:
        if self.matches:
            self.match_index = (self.match_index + direction) % len(self.matches)
            self._show_match()

    def _set_scroll(self, value: int) -> None:
        self.scroll = max(0, min(self.maximum_scroll, value))
        self._match_pinned = False
        self._pending_anchor = None

    def _drag(self, pointer_y: int) -> None:
        if self._dragging is None:
            return
        travel = max(1, self._scrollbar.height - self._thumb.height)
        distance = max(0, min(travel, pointer_y - self._dragging - self._scrollbar.top))
        self._set_scroll(round(self.maximum_scroll * (1 - distance / travel)))

    def handle_event(self, event: Any) -> bool:
        pg = self.pg
        if event.type == getattr(pg, "WINDOWFOCUSLOST", -1):
            self._dragging = None
            self._composition = ""
        elif event.type == pg.MOUSEWHEEL:
            self._set_scroll(self.scroll + event.y * 3)
        elif event.type == pg.MOUSEBUTTONDOWN:
            if event.button in {4, 5}:
                self._set_scroll(self.scroll + (3 if event.button == 4 else -3))
            elif event.button == 1:
                for hit, action in reversed(self._hits):
                    if not hit.collidepoint(event.pos):
                        continue
                    if action == "close":
                        self.close()
                        return True
                    if action == "search":
                        self._start_search(select=getattr(event, "clicks", 1) > 1)
                    elif action == "next":
                        self._next_match()
                    elif action == "previous":
                        self._next_match(-1)
                    elif action == "clear":
                        self.query = ""
                        self._query_selected = False
                        self._composition = ""
                        self._find_matches()
                    elif action == "scrollbar":
                        self._dragging = event.pos[1] - self._thumb.top if self._thumb.collidepoint(event.pos) else self._thumb.height // 2
                        self._drag(event.pos[1])
                    break
        elif event.type == pg.MOUSEMOTION and self._dragging is not None:
            self._drag(event.pos[1])
        elif event.type == pg.MOUSEBUTTONUP and getattr(event, "button", None) == 1:
            self._dragging = None
        elif event.type == pg.TEXTEDITING and self.searching:
            self._composition = "".join(character for character in str(event.text) if character.isprintable())
        elif event.type == pg.TEXTINPUT and self.searching:
            if self._query_selected:
                self.query = ""
                self._query_selected = False
            self.query += "".join(char for char in event.text if char.isprintable())[:max(0, 64 - len(self.query))]
            self._composition = ""
            self.match_index = 0
            self._find_matches()
            self._show_match()
        elif event.type == pg.KEYDOWN:
            key = event.key
            mod = getattr(event, "mod", 0)
            command = bool(mod & (pg.KMOD_CTRL | pg.KMOD_GUI))
            if self.searching and self._composition and key in {pg.K_RETURN, pg.K_KP_ENTER, pg.K_BACKSPACE, pg.K_DELETE}:
                # SDL's following text events commit or edit the composition.
                # The same key must not erase the saved query or cycle results.
                return False
            if key == pg.K_ESCAPE:
                if self._composition:
                    self._composition = ""
                elif self.searching:
                    self.close()
                else:
                    self.close()
                    return True
            elif key == pg.K_TAB:
                self.close()
                return True
            elif key == pg.K_f and command:
                self._start_search()
            elif key == pg.K_F3 or (key == pg.K_g and command):
                self._next_match(-1 if mod & pg.KMOD_SHIFT else 1)
            elif self.searching and key == pg.K_a and command:
                self._query_selected = True
            elif self.searching and key in {pg.K_BACKSPACE, pg.K_DELETE}:
                self.query = "" if self._query_selected or key == pg.K_DELETE else self.query[:-1]
                self._query_selected = False
                self._composition = ""
                self.match_index = 0
                self._find_matches()
                self._show_match()
            elif self.searching and key in {pg.K_RETURN, pg.K_KP_ENTER}:
                self._next_match(-1 if mod & pg.KMOD_SHIFT else 1)
            elif key in {pg.K_UP, pg.K_PAGEUP}:
                self._set_scroll(self.scroll + (1 if key == pg.K_UP else max(1, self.rows - 2)))
            elif key in {pg.K_DOWN, pg.K_PAGEDOWN} or (key == pg.K_SPACE and not self.searching):
                self._set_scroll(self.scroll - (1 if key == pg.K_DOWN else max(1, self.rows - 2)))
            elif key == pg.K_HOME:
                self._set_scroll(self.maximum_scroll)
            elif key == pg.K_END:
                self._set_scroll(0)
        return False

    def _measure(self, width: int) -> None:
        self._lines = []
        self._line_spans = []
        self._entry_starts = {}
        for entry, (text, color, bold) in enumerate(self.entries):
            self._entry_starts[entry] = len(self._lines)
            font = self.bold_font if bold else self.font
            base = 0
            for paragraph in text.split("\n"):
                normalized, spans = _normalized(paragraph)
                cursor = 0
                for line in wrap_text(paragraph, font, width):
                    target = _normalized(line)[0]
                    found = normalized.find(target, cursor) if target else cursor
                    found = max(cursor, found)
                    stop = min(len(spans), found + len(target))
                    begin_offset = spans[found][0] if found < len(spans) else len(paragraph)
                    end_offset = spans[stop - 1][1] if stop > found else begin_offset
                    self._lines.append((line, color, bold, entry))
                    self._line_spans.append((base + begin_offset, base + end_offset))
                    cursor = stop
                base += len(paragraph) + 1

    def _restore_anchor(self, anchor: tuple[int, int]) -> None:
        candidates = [index for index, line in enumerate(self._lines) if (line[3], self._line_spans[index][0]) <= anchor]
        line = candidates[-1] if candidates else 0
        self.scroll = max(0, min(self.maximum_scroll, self.maximum_scroll - line))

    def _text(self, surface: Any, text: str, position: Any, color: Any = PARCHMENT, *, font: Any = None) -> None:
        surface.blit((font or self.font).render(text, False, color), position)

    def _button(self, surface: Any, rect: Any, label: str, action: str, *, enabled: bool = True) -> None:
        self.pg.draw.rect(surface, INK, rect)
        self.pg.draw.rect(surface, TEAL if enabled else EDGE, rect, 1)
        text = self.small_font.render(label, False, PARCHMENT if enabled else MUTED)
        surface.blit(text, text.get_rect(center=rect.center))
        if enabled:
            self._hits.append((rect, action))

    def footer_lines(self) -> tuple[str, str]:
        """Report controls for the current input focus, including saved queries."""
        end = len(self._lines) - self.scroll
        start = max(0, end - self.rows)
        position = f"Lines {start + 1 if self._lines else 0}–{end} of {len(self._lines)}"
        if self.query.strip():
            result = f"Match {self.match_index + 1} of {len(self.matches)}" if self.matches else "No matches"
            position = f"{result}  /  {position}"
        if self.searching:
            controls = "Enter: next  Shift+Enter: previous  Esc: end search"
        elif self.query.strip():
            controls = "F3: next  Ctrl+F: edit search  Arrows / wheel: read"
        else:
            controls = "Ctrl+F: search  Arrows / wheel / PgUp / PgDn: read"
        return position, controls

    def draw(self, surface: Any, rect: Any) -> None:
        pg = self.pg
        rect = pg.Rect(rect)
        if rect.width < 260 or rect.height < 220:
            return
        old_anchor = self._pending_anchor or self.reading_anchor
        was_at_bottom = self.scroll == 0
        self._fonts(21 if rect.width >= 1700 else 19 if rect.width >= 1300 else 17)
        old_clip = surface.get_clip()
        surface.set_clip(rect.clip(old_clip))
        self._hits = []
        pg.draw.rect(surface, PANEL, rect)
        pg.draw.rect(surface, EDGE, rect, 1)
        pg.draw.line(surface, AMBER, (rect.left + 22, rect.top), (rect.left + 194, rect.top), 2)
        self._text(surface, "THE ROAD REMEMBERS", (rect.x + 22, rect.y + 18), AMBER, font=self.title_font)
        self._text(surface, "Your story, choices, and battle record.", (rect.x + 22, rect.y + 53), MUTED, font=self.small_font)
        field = pg.Rect(rect.x + 22, rect.y + 83, rect.width - 44, 36)
        controls_width = 111
        self._search_field = pg.Rect(field.x, field.y, max(1, field.width - controls_width), field.height)
        pg.draw.rect(surface, INK, self._search_field)
        pg.draw.rect(surface, AMBER if self.searching else EDGE, self._search_field, 1)
        self._hits.append((self._search_field, "search"))
        prefix = "Search: " if self.searching or self.query else ""
        displayed_query = "" if self._query_selected and self._composition else self.query
        text = displayed_query + self._composition + ("_" if self.searching else "") if prefix else "Ctrl+F or click to search"
        available = max(1, self._search_field.width - 20 - self.small_font.size(prefix)[0])
        clipped = False
        while text and self.small_font.size(text)[0] > available:
            text = text[1:]
            clipped = True
        if clipped:
            text = "…" + text[1:]
        text_x = self._search_field.x + 10
        if self._query_selected:
            pg.draw.rect(surface, (49, 69, 68), (text_x + self.small_font.size(prefix)[0], field.y + 6, self.small_font.size(text)[0], field.height - 12))
        self._text(surface, prefix + text, (text_x, field.y + 9), PARCHMENT, font=self.small_font)
        button_x = self._search_field.right + 6
        self._button(surface, pg.Rect(button_x, field.y, 30, 36), "<", "previous", enabled=bool(self.matches))
        self._button(surface, pg.Rect(button_x + 35, field.y, 30, 36), ">", "next", enabled=bool(self.matches))
        self._button(surface, pg.Rect(button_x + 70, field.y, 35, 36), "×", "clear", enabled=bool(self.query or self._composition))
        if self.searching:
            pg.key.set_text_input_rect(self._search_field)
        footer_height = max(72, self.small_font.get_linesize() * 3 + 14)
        footer_y = rect.bottom - footer_height
        content_width = max(1, min(1100, rect.width - 76))
        self._content = pg.Rect(rect.centerx - content_width // 2, field.bottom + 17, content_width, max(1, footer_y - field.bottom - 27))
        self.rows = max(1, self._content.height // self.line_height)
        key = (self._version, content_width, self._font_size)
        viewport = (key, self.rows)
        reflowed = self._layout_key != key or self._viewport_key != viewport
        if self._layout_key != key:
            self._measure(max(1, content_width - 18))
            self._layout_key = key
        self.maximum_scroll = max(0, len(self._lines) - self.rows)
        if self._pending_scroll is not None:
            self.scroll = min(self.maximum_scroll, self._pending_scroll)
        elif reflowed and self._match_pinned:
            self._show_match()
        elif reflowed and old_anchor and not was_at_bottom:
            self._restore_anchor(old_anchor)
        else:
            self.scroll = min(self.scroll, self.maximum_scroll)
        self._pending_scroll = None
        self._pending_anchor = None
        self._viewport_key = viewport
        end = len(self._lines) - self.scroll
        start = max(0, end - self.rows)
        color_map = {Color.YELLOW: AMBER, Color.CYAN: TEAL, Color.GREEN: TEAL, Color.RED: RED, Color.MAGENTA: (171, 145, 195), Color.DIM: MUTED}
        surface.set_clip(self._content.clip(rect).clip(old_clip))
        selected = self._match_positions[self.match_index] if self._match_positions else None
        for row, (line, color, bold, entry) in enumerate(self._lines[start:end]):
            y = self._content.y + row * self.line_height
            begin, stop = self._line_spans[start + row]
            if selected and entry == selected[0] and stop > selected[1] and begin < selected[2]:
                pg.draw.rect(surface, (51, 49, 38), (self._content.x, y, self._content.width - 14, self.line_height))
                pg.draw.rect(surface, AMBER, (self._content.x, y, 2, self.line_height))
            self._text(surface, line, (self._content.x + 6, y), color_map.get(color, PARCHMENT), font=self.bold_font if bold else self.font)
        if not self._lines:
            self._text(surface, "No story recorded yet.", (self._content.x + 6, self._content.y + 12), MUTED)
        surface.set_clip(rect.clip(old_clip))
        self._scrollbar = pg.Rect(min(rect.right - 22, self._content.right + 8), self._content.y, 7, self._content.height)
        pg.draw.rect(surface, INK, self._scrollbar)
        self._thumb = self._scrollbar.copy()
        if self.maximum_scroll:
            thumb_height = min(self._scrollbar.height, max(20, round(self._scrollbar.height * self.rows / max(1, len(self._lines)))))
            thumb_y = self._scrollbar.y + round((self._scrollbar.height - thumb_height) * (1 - self.scroll / self.maximum_scroll))
            self._thumb = pg.Rect(self._scrollbar.x, thumb_y, self._scrollbar.width, thumb_height)
            pg.draw.rect(surface, TEAL, self._thumb)
            self._hits.append((self._scrollbar.inflate(10, 0), "scrollbar"))
        pg.draw.line(surface, EDGE, (rect.left + 22, footer_y), (rect.right - 22, footer_y))
        return_label = "Return [Tab]" if self.searching else "Return [Tab/Esc]"
        return_width = self.small_font.size(return_label)[0] + 26
        self._button(surface, pg.Rect(rect.right - 22 - return_width, footer_y + 17, return_width, 33), return_label, "close")
        text_width = max(1, rect.width - return_width - 66)
        y = footer_y + 9
        for text in self.footer_lines():
            for line in wrap_text(text, self.small_font, text_width):
                self._text(surface, line, (rect.x + 22, y), MUTED, font=self.small_font)
                y += self.small_font.get_linesize() + 2
        surface.set_clip(old_clip)
