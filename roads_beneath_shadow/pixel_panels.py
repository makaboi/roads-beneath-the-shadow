"""Read-only, main-thread adventure panels for the pixel presentation.

The story worker supplies plain snapshots.  This module never imports pygame,
reads game state, or changes a character: it returns explicit actions for the
engine to validate.  Closing a panel leaves the caller's story page intact.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


INK = (16, 21, 27)
PANEL = (23, 31, 38)
CARD = (29, 39, 46)
EDGE = (65, 78, 79)
PARCHMENT = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 156, 151)
MUTED = (159, 161, 150)
RED = (219, 132, 113)

_TITLES = {
    "inventory": ("THE TRAVELER'S PACK", "Equipment, provisions, and things worth keeping"),
    "character": ("THE TRAVELER", "A life shaped by the road"),
    "journal": ("THE ROAD JOURNAL", "Promises to keep. Clues to remember."),
    "map": ("ROADS REMEMBERED", "Your journey through the shadow"),
    "saves": ("CAMPFIRE MEMORIES", "Keep a place on the road"),
    "chronicle": ("THE TRAVELER'S CHRONICLE", "The roads you finished and the deeds remembered"),
    "information": ("NOTES FROM THE ROAD", "Read closely, then return to your journey"),
}
_TABS = {
    "inventory": (("All items", "all"), ("Equipment", "gear"), ("Supplies", "supplies"), ("Keepsakes", "quest")),
    "journal": (("Active quests", "active"), ("Completed", "completed"), ("Clues", "clues")),
}
_ICONS = {
    "weapon": ("..........aa", ".........aa.", "........aa..", ".......aa...", "......aa....", ".....aa.....", "..a.aa......", "...aaa......", "...aaa......", "..aa..a.....", ".aa.........", "............"),
    "armor": ("..aaaaaa....", ".aaaaaaaa...", ".aa....aa...", ".aa....aa...", ".aaa..aaa...", "..aaaaaa....", "..aaaaaa....", "...aaaa.....", "....aa......", "............", "............", "............"),
    "consumable": ("............", ".....aa.....", ".....aaa....", "..aa..aa....", "..aaa.a.....", "...aaaa.....", ".....a.aaa..", ".....aaaaa..", ".....a..a...", "....aa......", "...aa.......", "............"),
    "quest": (".....a......", "..a..a..a...", "...aaa.a....", "....aaa.....", "aaaaaaaaaaa.", "....aaa.....", "...a.aaa....", "..a..a..a...", ".....a......", "............", "............", "............"),
}


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _wrap(text: Any, font: Any, width: int) -> list[str]:
    """Keep every character, even for names longer than the available width."""
    width = max(1, width)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if font.size(candidate)[0] <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while word and font.size(word)[0] > width:
                cut = 1
                while cut < len(word) and font.size(word[:cut + 1])[0] <= width:
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines or [""]


class PanelView:
    """A snapshot-driven modal. ``handle_event`` returns (handled, result).

    Results are ``{'action': 'close'}``, inventory ``equip`` / ``use`` with
    ``item_id``, or saves ``select_slot`` with ``slot``.  An action never edits
    the supplied snapshot.  Tab changes categories, arrows browse, and Escape
    always returns to the current scene.  pygame must already be initialized.
    """

    def __init__(self, pg: Any) -> None:
        self.pg = pg
        self.active = False
        self.kind = "inventory"
        self.data: dict[str, Any] = {}
        self.selected = 0
        self.tab_index = 0
        self.scroll = 0
        self.detail_scroll = 0
        self.max_scroll = 0
        self.max_detail_scroll = 0
        self.hit_targets: list[tuple[Any, str, Any]] = []
        self.content_rect = pg.Rect(0, 0, 0, 0)
        self.detail_rect = pg.Rect(0, 0, 0, 0)
        self._ensure_selection = True
        self._font_size = 0
        self._portraits: dict[tuple[int, int], Any] = {}
        self._fonts(16)

    def _fonts(self, size: int) -> None:
        if self._font_size == size:
            return
        self._font_size = size
        name = "dejavusansmono,courier,monospace"
        self.font = self.pg.font.SysFont(name, size)
        self.small_font = self.pg.font.SysFont(name, max(11, size - 3))
        self.bold_font = self.pg.font.SysFont(name, size, bold=True)
        self.title_font = self.pg.font.SysFont(name, size + 8, bold=True)
        self.line_height = self.font.get_linesize() + 3

    def open(self, kind: str, data: dict[str, Any]) -> None:
        if kind not in _TITLES:
            raise ValueError(f"Unknown adventure panel: {kind}")
        self.kind = kind
        self.data = deepcopy(data)
        self.active = True
        self.selected = self.tab_index = self.scroll = self.detail_scroll = 0
        self.max_scroll = self.max_detail_scroll = 0
        self.hit_targets = []
        self._ensure_selection = True

    def close(self) -> None:
        self.active = False
        self.hit_targets = []

    @property
    def tab(self) -> str:
        tabs = _TABS.get(self.kind, ())
        return tabs[self.tab_index][1] if tabs else ""

    def visible_items(self) -> list[dict[str, Any]]:
        """Return a stable, categorized item order without changing the source."""
        items = [item for item in self.data.get("items", []) if isinstance(item, dict)]
        filters = {
            "gear": lambda item: bool(item.get("slot")) or item.get("kind") in {"weapon", "armor"},
            "supplies": lambda item: item.get("kind") == "consumable",
            "quest": lambda item: item.get("kind") in {"quest", "key", "keepsake"},
        }
        if self.tab in filters:
            items = [item for item in items if filters[self.tab](item)]
        order = {"weapon": 0, "armor": 1, "consumable": 2, "quest": 3}
        return sorted(items, key=lambda item: (order.get(item.get("kind"), 4), str(item.get("name", "")).casefold(), str(item.get("id", ""))))

    def _selected_item(self) -> dict[str, Any] | None:
        items = self.visible_items()
        if not items:
            return None
        self.selected = max(0, min(self.selected, len(items) - 1))
        return items[self.selected]

    def _item_action(self) -> dict[str, Any] | None:
        item = self._selected_item()
        if not item or not item.get("id") or _number(item.get("count", 1)) < 1:
            return None
        if item.get("slot") and not item.get("equipped"):
            return {"action": "equip", "item_id": item["id"]}
        if _number(item.get("healing")) > 0:
            return {"action": "use", "item_id": item["id"]}
        return None

    def _change_tab(self, direction: int) -> None:
        tabs = _TABS.get(self.kind, ())
        if tabs:
            self.tab_index = (self.tab_index + direction) % len(tabs)
            self.selected = self.scroll = self.detail_scroll = 0
            self._ensure_selection = True

    def _move_selection(self, direction: int) -> None:
        entries = self.visible_items() if self.kind == "inventory" else self.data.get("slots", [])
        if entries:
            self.selected = max(0, min(self.selected + direction, len(entries) - 1))
            self.detail_scroll = 0
            self._ensure_selection = True

    def _scroll(self, amount: int, *, detail: bool = False) -> None:
        if detail:
            self.detail_scroll = max(0, min(self.detail_scroll + amount, self.max_detail_scroll))
        else:
            self.scroll = max(0, min(self.scroll + amount, self.max_scroll))
        self._ensure_selection = False

    def handle_event(self, event: Any) -> tuple[bool, dict[str, Any] | None]:
        if not self.active:
            return False, None
        pg = self.pg
        if event.type in {pg.QUIT, pg.VIDEORESIZE, getattr(pg, "WINDOWRESIZED", -1)}:
            return False, None
        if event.type == pg.KEYDOWN:
            key = event.key
            if key == pg.K_F11:
                return False, None
            if key == pg.K_ESCAPE:
                self.close()
                return True, {"action": "close"}
            if key == pg.K_TAB:
                self._change_tab(-1 if getattr(event, "mod", 0) & pg.KMOD_SHIFT else 1)
            elif key in {pg.K_LEFT, pg.K_RIGHT}:
                self._change_tab(-1 if key == pg.K_LEFT else 1)
            elif key in {pg.K_UP, pg.K_DOWN}:
                direction = -1 if key == pg.K_UP else 1
                if self.kind in {"inventory", "saves"}:
                    self._move_selection(direction)
                else:
                    self._scroll(direction * self.line_height * 2)
            elif key in {pg.K_PAGEUP, pg.K_PAGEDOWN}:
                direction = -1 if key == pg.K_PAGEUP else 1
                detail = self.kind == "inventory" and bool(getattr(event, "mod", 0) & pg.KMOD_SHIFT)
                self._scroll(direction * max(80, self.content_rect.height - 40), detail=detail)
            elif key in {pg.K_HOME, pg.K_END}:
                if self.kind in {"inventory", "saves"}:
                    entries = self.visible_items() if self.kind == "inventory" else self.data.get("slots", [])
                    self.selected = max(0, len(entries) - 1) if key == pg.K_END else 0
                    self._ensure_selection = True
                    self.detail_scroll = 0
                else:
                    self.scroll = self.max_scroll if key == pg.K_END else 0
            elif key in {pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE}:
                if self.kind == "inventory":
                    return True, self._item_action()
                if self.kind == "saves":
                    return True, self._slot_action()
                self.close()
                return True, {"action": "close"}
            return True, None
        if event.type == pg.MOUSEWHEEL:
            position = getattr(event, "pos", pg.mouse.get_pos())
            detail = self.kind == "inventory" and self.detail_rect.collidepoint(position)
            self._scroll(-event.y * self.line_height * 3, detail=detail)
            return True, None
        if event.type == pg.MOUSEBUTTONDOWN:
            if event.button in {4, 5}:
                detail = self.kind == "inventory" and self.detail_rect.collidepoint(event.pos)
                self._scroll((-1 if event.button == 4 else 1) * self.line_height * 3, detail=detail)
                return True, None
            if event.button == 1:
                for rect, target, value in reversed(self.hit_targets):
                    if not rect.collidepoint(event.pos):
                        continue
                    if target == "close":
                        self.close()
                        return True, {"action": "close"}
                    if target == "tab":
                        self.tab_index = value
                        self.selected = self.scroll = self.detail_scroll = 0
                        self._ensure_selection = True
                    elif target == "item":
                        self.selected = value
                        self.detail_scroll = 0
                        self._ensure_selection = True
                    elif target == "item_action":
                        return True, self._item_action()
                    elif target == "slot":
                        self.selected = value
                        self._ensure_selection = True
                    elif target == "slot_action":
                        self.selected = value
                        return True, self._slot_action()
                    break
            return True, None
        # A modal consumes pointer/text events so they cannot select a story
        # choice behind it. Window lifecycle events still belong to the caller.
        return event.type in {pg.MOUSEMOTION, pg.MOUSEBUTTONUP, pg.KEYUP, pg.TEXTINPUT, pg.TEXTEDITING}, None

    def _text(self, screen: Any, text: Any, x: int, y: int, color: Any = PARCHMENT, *, font: Any = None) -> None:
        screen.blit((font or self.font).render(str(text), False, color), (x, y))

    def _paragraph(self, screen: Any, text: Any, x: int, y: int, width: int, color: Any = MUTED, *, font: Any = None) -> int:
        font = font or self.font
        line_height = font.get_linesize() + 3
        for line in _wrap(text, font, width):
            self._text(screen, line, x, y, color, font=font)
            y += line_height
        return y

    def _icon(self, screen: Any, kind: str, x: int, y: int, color: Any = AMBER, scale: int = 2) -> None:
        pattern = _ICONS.get(kind, _ICONS["quest"])
        for row, pixels in enumerate(pattern):
            for column, pixel in enumerate(pixels):
                if pixel == "a":
                    self.pg.draw.rect(screen, color, (x + column * scale, y + row * scale, scale, scale))

    def _portrait(self, screen: Any, row: int, x: int, y: int, scale: int = 4) -> bool:
        """Use the same nearest-neighbor sprites the player meets on the road."""
        key = (row, scale)
        if key not in self._portraits:
            try:
                atlas = self.pg.image.load(str(Path(__file__).with_name("pixel_assets") / "world-characters.png"))
                frame = atlas.subsurface(self.pg.Rect(0, row * 24, 20, 24))
                self._portraits[key] = self.pg.transform.scale(frame, (20 * scale, 24 * scale))
            except (OSError, ValueError, self.pg.error):
                self._portraits[key] = None
        portrait = self._portraits[key]
        if portrait is None:
            return False
        screen.blit(portrait, (x, y))
        return True

    def _button(self, screen: Any, rect: Any, label: str, target: str, value: Any = None, *, primary: bool = False, enabled: bool = True) -> None:
        pg = self.pg
        pg.draw.rect(screen, INK if not enabled else (47, 58, 57) if primary else CARD, rect)
        pg.draw.rect(screen, AMBER if primary and enabled else EDGE, rect, 1)
        text = self.bold_font.render(label, False, PARCHMENT if primary and enabled else MUTED)
        screen.blit(text, text.get_rect(center=rect.center))
        clip = screen.get_clip()
        visible = rect.clip(clip)
        if enabled and visible.width and visible.height:
            self.hit_targets.append((visible, target, value))

    def _scrollbar(self, screen: Any, rect: Any, offset: int, maximum: int) -> None:
        if maximum <= 0 or rect.height < 20:
            return
        track = self.pg.Rect(rect.right - 5, rect.top + 2, 3, rect.height - 4)
        self.pg.draw.rect(screen, EDGE, track)
        height = max(24, int(track.height * rect.height / (rect.height + maximum)))
        top = track.top + int((track.height - height) * min(offset, maximum) / maximum)
        self.pg.draw.rect(screen, AMBER, (track.left, top, 3, height))

    def draw(self, screen: Any, rect: Any) -> None:
        if not self.active:
            return
        pg = self.pg
        rect = pg.Rect(rect)
        if rect.width < 260 or rect.height < 220:
            return
        self._fonts(14 if rect.width < 900 else 16)
        old_clip = screen.get_clip()
        screen.set_clip(rect)
        screen.fill(INK, rect)
        frame = rect.inflate(-max(16, min(56, rect.width // 20)), -28)
        pg.draw.rect(screen, PANEL, frame)
        pg.draw.rect(screen, EDGE, frame, 1)
        pg.draw.line(screen, AMBER, (frame.left + 18, frame.top), (frame.left + min(frame.width - 18, 180), frame.top), 2)
        self.hit_targets = []
        padding = 22 if rect.width >= 700 else 14
        left, width = frame.left + padding, frame.width - padding * 2
        title, subtitle = _TITLES[self.kind]
        if self.kind == "information":
            title = str(self.data.get("title", title))
            subtitle = str(self.data.get("subtitle", subtitle))
        title_y = frame.top + 20
        self._icon(screen, "quest", left, title_y + 2, AMBER)
        title_bottom = self._paragraph(screen, title, left + 36, title_y, width - 36, PARCHMENT, font=self.title_font)
        subtitle_bottom = self._paragraph(screen, subtitle, left, title_bottom + 5, width, MUTED, font=self.small_font)
        footer_height = 72 if width < 600 else 60
        footer_y = frame.bottom - footer_height
        pg.draw.line(screen, EDGE, (left, footer_y), (left + width, footer_y))
        return_label = "Return to the main menu  [Esc]" if self.kind == "chronicle" else "Return to the road  [Esc]"
        button_width = min(width, self.bold_font.size(return_label)[0] + 26)
        self._button(screen, pg.Rect(left + width - button_width, footer_y + 12, button_width, 34), return_label, "close")
        hint = "Tab: categories   Arrows: browse"
        if self.kind == "inventory":
            hint = "Enter: equip / use   Shift+PgDn: details"
        elif self.kind == "saves":
            hint = "Arrows: choose   Enter: select"
        elif self.kind not in _TABS:
            hint = "Scroll to read   Enter: return"
        if width > button_width + self.small_font.size(hint)[0] + 20:
            self._text(screen, hint, left, footer_y + 21, MUTED, font=self.small_font)
        elif footer_height > 60:
            self._text(screen, hint, left, footer_y + 51, MUTED, font=self.small_font)
        content_y = subtitle_bottom + 18
        tabs = _TABS.get(self.kind, ())
        if tabs:
            tab_width = width // len(tabs)
            for index, (label, _) in enumerate(tabs):
                tab_rect = pg.Rect(left + index * tab_width, content_y, tab_width - 5, 36)
                pg.draw.rect(screen, CARD if index == self.tab_index else PANEL, tab_rect)
                label_font = self.small_font if self.bold_font.size(label)[0] > tab_rect.width - 12 else self.bold_font
                text = label_font.render(label, False, AMBER if index == self.tab_index else MUTED)
                screen.blit(text, text.get_rect(center=tab_rect.center))
                if index == self.tab_index:
                    pg.draw.line(screen, AMBER, (tab_rect.left, tab_rect.bottom), (tab_rect.right, tab_rect.bottom), 2)
                self.hit_targets.append((tab_rect, "tab", index))
            content_y += 52
        self.content_rect = pg.Rect(left, content_y, width, max(1, footer_y - content_y - 16))
        self.detail_rect = pg.Rect(0, 0, 0, 0)
        if self.kind == "inventory":
            self._draw_inventory(screen)
        else:
            screen.set_clip(self.content_rect.clip(rect))
            render = {
                "character": self._draw_character, "journal": self._draw_journal,
                "map": self._draw_map, "saves": self._draw_saves,
                "chronicle": self._draw_chronicle, "information": self._draw_information,
            }[self.kind]
            height = render(screen, self.content_rect.left, self.content_rect.top - self.scroll, self.content_rect.width - 12)
            self.max_scroll = max(0, height - self.content_rect.height)
            self.scroll = min(self.scroll, self.max_scroll)
            screen.set_clip(rect)
            self._scrollbar(screen, self.content_rect, self.scroll, self.max_scroll)
        screen.set_clip(old_clip)

    def _draw_inventory(self, screen: Any) -> None:
        pg = self.pg
        region = self.content_rect
        gap = 20 if region.width >= 700 else 12
        left_width = max(100, (region.width - gap) * 46 // 100)
        pack_rect = pg.Rect(region.left, region.top, left_width, region.height)
        self.detail_rect = pg.Rect(pack_rect.right + gap, region.top, region.width - left_width - gap, region.height)
        items = self.visible_items()
        self.selected = min(self.selected, max(0, len(items) - 1))
        card_heights = [max(82, len(_wrap(item.get("name", "Unnamed item"), self.bold_font, left_width - 68)) * self.line_height + 44) for item in items]
        self.max_scroll = max(0, sum(height + 8 for height in card_heights) - 8 - pack_rect.height)
        if items and self._ensure_selection:
            top = sum(height + 8 for height in card_heights[:self.selected])
            bottom = top + card_heights[self.selected]
            if top < self.scroll:
                self.scroll = top
            elif bottom > self.scroll + pack_rect.height:
                self.scroll = bottom - pack_rect.height
            self._ensure_selection = False
        self.scroll = min(self.scroll, self.max_scroll)
        screen.set_clip(pack_rect)
        y = pack_rect.top - self.scroll
        for index, (item, height) in enumerate(zip(items, card_heights)):
            card = pg.Rect(pack_rect.left, y, pack_rect.width - 10, height)
            if card.colliderect(pack_rect):
                pg.draw.rect(screen, (40, 51, 52) if index == self.selected else CARD, card)
                pg.draw.rect(screen, AMBER if index == self.selected else EDGE, card, 1)
                self._icon(screen, item.get("kind", "quest"), card.left + 13, card.top + 17, TEAL if item.get("kind") == "consumable" else AMBER)
                bottom = self._paragraph(screen, item.get("name", "Unnamed item"), card.left + 49, card.top + 12, card.width - 58, PARCHMENT, font=self.bold_font)
                markers = [f"x{_number(item.get('count', 1))}", str(item.get("kind", "item")).capitalize()]
                if item.get("equipped"):
                    markers.append("EQUIPPED")
                self._paragraph(screen, "  /  ".join(markers), card.left + 49, bottom + 5, card.width - 58, TEAL if item.get("equipped") else MUTED, font=self.small_font)
                self.hit_targets.append((card.clip(pack_rect), "item", index))
            y += height + 8
        if not items:
            self._paragraph(screen, "Your pack is empty." if self.tab == "all" else "Nothing in this category yet.", pack_rect.left + 12, pack_rect.top + 18, pack_rect.width - 30)
        screen.set_clip(self.detail_rect)
        screen.fill(CARD, self.detail_rect)
        selected = self._selected_item()
        if selected:
            detail_height = self._draw_item_detail(screen, selected)
            self.max_detail_scroll = max(0, detail_height - self.detail_rect.height)
            self.detail_scroll = min(self.detail_scroll, self.max_detail_scroll)
        else:
            self.max_detail_scroll = self.detail_scroll = 0
            self._paragraph(screen, "Every object on the road has a story. Select an item to inspect it.", self.detail_rect.left + 18, self.detail_rect.top + 24, self.detail_rect.width - 36)
        screen.set_clip(region)
        self._scrollbar(screen, pack_rect, self.scroll, self.max_scroll)
        self._scrollbar(screen, self.detail_rect, self.detail_scroll, self.max_detail_scroll)

    def _draw_item_detail(self, screen: Any, item: dict[str, Any]) -> int:
        pg = self.pg
        rect = self.detail_rect
        start_y = rect.top - self.detail_scroll
        x, y, width = rect.left + 20, start_y + 24, rect.width - 40
        self._icon(screen, item.get("kind", "quest"), x, y, TEAL if item.get("kind") == "consumable" else AMBER, 3)
        y += 49
        y = self._paragraph(screen, item.get("name", "Unnamed item"), x, y, width, PARCHMENT, font=self.title_font) + 8
        label = "Currently equipped" if item.get("equipped") else str(item.get("kind", "item")).capitalize()
        self._text(screen, label, x, y, TEAL if item.get("equipped") else AMBER, font=self.small_font)
        y += 33
        y = self._paragraph(screen, item.get("description", ""), x, y, width) + 23
        for key, label, color in (("attack", "Attack", AMBER), ("defense", "Armor", TEAL), ("healing", "Restores health", TEAL)):
            amount = _number(item.get(key))
            if amount:
                self._text(screen, f"{label}  +{amount}", x, y, color, font=self.bold_font)
                y += self.line_height + 6
        if item.get("slot"):
            equipped = next((other for other in self.data.get("items", []) if isinstance(other, dict) and other.get("slot") == item.get("slot") and other.get("equipped")), None)
            if equipped and equipped.get("id") != item.get("id"):
                y += 8
                y = self._paragraph(screen, f"Compared with {equipped.get('name', 'equipped gear')}", x, y, width, MUTED, font=self.small_font) + 4
                for key, label in (("attack", "attack"), ("defense", "armor")):
                    difference = _number(item.get(key)) - _number(equipped.get(key))
                    if difference:
                        self._text(screen, f"{difference:+d} {label}", x, y, TEAL if difference > 0 else RED)
                        y += self.line_height
        y += 22
        action = self._item_action()
        if action:
            label = "Equip item  [Enter]" if action["action"] == "equip" else "Use item  [Enter]"
            if self.bold_font.size(label)[0] > width - 10:
                label = "Equip" if action["action"] == "equip" else "Use item"
            self._button(screen, pg.Rect(x, y, width, 43), label, "item_action", primary=True)
            y += 57
        else:
            message = "This gear is already equipped." if item.get("equipped") else "Available during combat." if item.get("kind") == "consumable" else "A keepsake for the journey."
            y = self._paragraph(screen, message, x, y, width, MUTED, font=self.small_font) + 12
        return y - start_y + 10

    def _section(self, screen: Any, title: str, x: int, y: int, width: int) -> int:
        self._text(screen, title.upper(), x, y, AMBER, font=self.bold_font)
        y += self.line_height + 8
        self.pg.draw.line(screen, EDGE, (x, y), (x + width, y))
        return y + 15

    def _meter(self, screen: Any, label: str, value: Any, maximum: Any, x: int, y: int, width: int, color: Any) -> int:
        value, maximum = _number(value), max(1, _number(maximum, 1))
        self._text(screen, label, x, y, MUTED, font=self.small_font)
        text = self.bold_font.render(f"{value} / {maximum}", False, PARCHMENT)
        screen.blit(text, (x + width - text.get_width(), y - 1))
        y += self.line_height
        bar = self.pg.Rect(x, y, width, 11)
        self.pg.draw.rect(screen, INK, bar)
        fill = max(0, min(width, int(width * value / maximum)))
        self.pg.draw.rect(screen, color, (x, y, fill, 11))
        self.pg.draw.rect(screen, EDGE, bar, 1)
        return y + 25

    def _draw_character(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        character = self.data.get("character", self.data)
        # The traveler portrait and companion portraits share the exploration
        # atlas, keeping the sheet visually connected to the playable world.
        header_x = x + 116 if width >= 500 else x
        if width >= 500:
            self.pg.draw.rect(screen, CARD, (x, y, 94, 108))
            self.pg.draw.rect(screen, EDGE, (x, y, 94, 108), 1)
            self._portrait(screen, 0, x + 7, y + 6)
        header_width = width - (header_x - x)
        header_top = y
        y = self._paragraph(screen, character.get("name", "Traveler"), header_x, y + 4, header_width, PARCHMENT, font=self.title_font) + 5
        origin = character.get("origin_label", character.get("origin_name", character.get("origin", "A traveler of the old roads")))
        y = self._paragraph(screen, str(origin).replace("_", " ").title(), header_x, y, header_width, TEAL) + 13
        if character.get("origin_description"):
            y = self._paragraph(screen, character["origin_description"], header_x, y, header_width) + 8
        y = max(y + 18, header_top + 133 if width >= 500 else y + 18)
        if width >= 760:
            column_width = (width - 44) // 2
            condition_end = self._draw_character_condition(screen, character, x, y, column_width)
            party_end = self._draw_character_party(screen, character, x + column_width + 44, y, column_width)
            self.pg.draw.line(screen, EDGE, (x + column_width + 22, y), (x + column_width + 22, max(condition_end, party_end) - 12))
            return max(condition_end, party_end) - start_y + 8
        y = self._draw_character_condition(screen, character, x, y, width) + 12
        y = self._draw_character_party(screen, character, x, y, width)
        return y - start_y + 8

    def _draw_character_condition(self, screen: Any, character: dict[str, Any], x: int, y: int, width: int) -> int:
        y = self._section(screen, "Condition", x, y, width)
        y = self._meter(screen, "Health", character.get("hp", 0), character.get("max_hp", 1), x, y, width, RED)
        y = self._meter(screen, "Focus", character.get("focus", 0), character.get("max_focus", 3), x, y, width, TEAL)
        half = max(70, (width - 16) // 2)
        for column, (label, key, color) in enumerate((("HOPE", "hope", AMBER), ("CORRUPTION", "corruption", RED))):
            box = self.pg.Rect(x + column * (half + 16), y, half, 59)
            self.pg.draw.rect(screen, CARD, box)
            self._text(screen, label, box.left + 12, box.top + 10, color, font=self.small_font)
            self._text(screen, character.get(key, 0), box.left + 12, box.top + 28, PARCHMENT, font=self.bold_font)
        y += 82
        y = self._section(screen, "Attributes", x, y, width)
        attributes = character.get("attributes", self.data.get("attributes", {}))
        if not isinstance(attributes, dict):
            attributes = {}
        for key in ("strength", "cunning", "will"):
            value = attributes.get(key, character.get(key, 0))
            self._text(screen, key.capitalize(), x, y, MUTED)
            self._text(screen, value, x + width - 42, y, PARCHMENT, font=self.bold_font)
            y += self.line_height + 13
        ability_name = character.get("ability_name", character.get("ability", self.data.get("ability_name", self.data.get("ability"))))
        if ability_name:
            y += 10
            y = self._paragraph(screen, ability_name, x, y, width, TEAL, font=self.bold_font) + 5
            y = self._paragraph(screen, character.get("ability_description", self.data.get("ability_description", "")), x, y, width) + 15
        return y + 8

    def _draw_character_party(self, screen: Any, character: dict[str, Any], x: int, y: int, width: int) -> int:
        y = self._section(screen, "Equipment", x, y, width)
        gear = character.get("gear", self.data.get("gear", {}))
        if not isinstance(gear, dict):
            gear = {}
        for slot in ("weapon", "armor"):
            item = gear.get(slot, character.get(slot))
            if isinstance(item, dict):
                name = item.get("name", "None")
            else:
                name = (str(item).replace("_", " ").title() if "_" in str(item) else str(item)) if item else ("Unarmed" if slot == "weapon" else "Travel clothes")
            self._icon(screen, slot, x, y + 2, AMBER if slot == "weapon" else TEAL)
            y = self._paragraph(screen, f"{slot.capitalize()}: {name}", x + 38, y, width - 38, PARCHMENT) + 18
            bonus_key, bonus_label = ("weapon_attack", "attack") if slot == "weapon" else ("armor_defense", "armor")
            if _number(character.get(bonus_key)):
                self._text(screen, f"+{_number(character[bonus_key])} {bonus_label}", x + 38, y - 10, TEAL, font=self.small_font)
                y += self.small_font.get_linesize() + 3
        companions = self.data.get("companions", character.get("companions", []))
        y += 12
        y = self._section(screen, "Companions", x, y, width)
        if not companions:
            y = self._paragraph(screen, "The road is quiet. No companions are traveling with you.", x, y, width) + 10
        for companion in companions:
            if not isinstance(companion, dict):
                companion = {"name": str(companion)}
            trust = _number(companion.get("trust"))
            present = companion.get("present", True)
            status = "Traveling with you" if present else "Elsewhere on the road"
            trust_label = "Trusted" if trust >= 2 else "Steady" if trust >= 0 else "Wary"
            top = y
            portrait_row = {"mara": 4, "tobin": 5, "calenor": 6}.get(str(companion.get("name", "")).casefold())
            text_x = x + (69 if portrait_row is not None else 14)
            text_width = width - (text_x - x) - 14
            name_height = len(_wrap(companion.get("name", "Companion"), self.bold_font, text_width)) * self.line_height
            status_height = len(_wrap(f"{status}  /  {trust_label} ({trust:+d})", self.small_font, text_width)) * (self.small_font.get_linesize() + 3)
            height = max(88, name_height + status_height + 32)
            self.pg.draw.rect(screen, CARD, (x, y, width, height))
            if portrait_row is not None:
                self._portrait(screen, portrait_row, x + 12, y + 15, 2)
            y = self._paragraph(screen, companion.get("name", "Companion"), text_x, y + 12, text_width, PARCHMENT, font=self.bold_font) + 5
            y = self._paragraph(screen, f"{status}  /  {trust_label} ({trust:+d})", text_x, y, text_width, TEAL if present and trust >= 0 else MUTED, font=self.small_font)
            y = max(y + 12, top + height + 10)
        return y + 8

    def _journal_entries(self) -> list[Any]:
        aliases = {
            "active": ("activequests", "active_quests", "quests"),
            "completed": ("completedquests", "completed_quests"),
            "clues": ("clues", "journal"),
        }
        for key in aliases[self.tab]:
            if key in self.data:
                return self.data[key] or []
        return []

    def _draw_journal(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        entries = self._journal_entries()
        if not entries:
            messages = {"active": "No unfinished promises. New quests will appear as the road unfolds.", "completed": "Your completed quests will be remembered here.", "clues": "No clues recorded yet. Listen closely, and keep your eyes on the road."}
            return self._paragraph(screen, messages[self.tab], x + 18, y + 20, width - 36) - start_y + 25
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                title = entry.get("title", entry.get("name", "A note from the road"))
                description = entry.get("description", entry.get("text", ""))
            else:
                title, description = str(entry), ""
            title_lines = _wrap(title, self.bold_font, width - 66)
            body_lines = _wrap(description, self.font, width - 66) if description else []
            height = 30 + len(title_lines) * self.line_height + len(body_lines) * self.line_height + (12 if body_lines else 8)
            card = self.pg.Rect(x, y, width, height)
            self.pg.draw.rect(screen, CARD, card)
            self.pg.draw.rect(screen, EDGE, card, 1)
            self.pg.draw.rect(screen, TEAL if self.tab == "completed" else AMBER, (x, y, 3, height))
            self._text(screen, f"{index + 1:02d}", x + 13, y + 15, TEAL if self.tab == "completed" else AMBER, font=self.small_font)
            text_y = self._paragraph(screen, title, x + 48, y + 13, width - 66, PARCHMENT, font=self.bold_font)
            if description:
                self._paragraph(screen, description, x + 48, text_y + 8, width - 66)
            y += height + 13
        return y - start_y

    def _draw_map(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        route = self.data.get("route", self.data.get("locations", []))
        if not route:
            route = [{"name": name, "visited": True} for name in self.data.get("visited", [])]
        if not route:
            return self._paragraph(screen, "The first step is still ahead. Places you have visited will appear here.", x + 18, y + 20, width - 36) - start_y + 25
        if self.data.get("chapter"):
            self._text(screen, f"CHAPTER {self.data['chapter']}", x, y, TEAL, font=self.small_font)
            y += 35
        for location in route:
            if not isinstance(location, dict):
                location = {"name": str(location), "visited": True}
            current = location.get("current", False)
            visited = location.get("visited", False)
            color = AMBER if current else TEAL if visited else EDGE
            title = location.get("name", "Unknown road")
            if not visited and not current and location.get("hidden", False):
                title = "An unexplored road"
            title_lines = _wrap(title, self.bold_font, width - 67)
            description = location.get("description", "")
            height = max(74, 32 + len(title_lines) * self.line_height)
            if description:
                height += len(_wrap(description, self.font, width - 67)) * self.line_height + 7
            self.pg.draw.line(screen, EDGE, (x + 15, y), (x + 15, y + height + 12), 2)
            self.pg.draw.rect(screen, color, (x + 9, y + 14, 13, 13))
            if current:
                self.pg.draw.rect(screen, AMBER, (x + 5, y + 10, 21, 21), 1)
            bottom = self._paragraph(screen, title, x + 43, y + 9, width - 67, PARCHMENT if visited or current else MUTED, font=self.bold_font)
            label = "You are here" if current else "Visited" if visited else "Ahead on the road"
            bottom = self._paragraph(screen, label, x + 43, bottom + 3, width - 67, color, font=self.small_font)
            if description:
                self._paragraph(screen, description, x + 43, bottom + 7, width - 67)
            y += height + 14
        return y - start_y + 8

    def _draw_chronicle(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        completed = max(0, _number(self.data.get("completed_runs")))
        y = self._paragraph(screen, f"Completed journeys: {completed}", x, y, width, TEAL, font=self.bold_font) + 14
        if not completed:
            y = self._paragraph(screen, "Your chronicle begins when you finish a road. Your endings and earned achievements will be remembered here.", x, y, width) + 20
        origins = self.data.get("origins", [])
        y = self._paragraph(screen, "Backgrounds completed", x, y, width, AMBER, font=self.bold_font) + 6
        y = self._paragraph(screen, ", ".join(str(name) for name in origins) or "None yet", x, y, width) + 24
        y = self._paragraph(screen, "Endings witnessed", x, y, width, AMBER, font=self.bold_font) + 8
        endings = self.data.get("endings", [])
        if not endings:
            y = self._paragraph(screen, "No ending recorded yet.", x, y, width) + 9
        for ending in endings:
            if isinstance(ending, dict):
                count = max(0, _number(ending.get("count")))
                y = self._paragraph(screen, f"{ending.get('name', 'A completed road')}  /  {count}", x + 12, y, width - 12, PARCHMENT) + 8
        achievements = [entry for entry in self.data.get("achievements", []) if isinstance(entry, dict)]
        earned = sum(bool(entry.get("earned")) for entry in achievements)
        y = self._paragraph(screen, f"Achievements  /  {earned} of {len(achievements)} earned", x, y + 14, width, AMBER, font=self.bold_font) + 14
        for achievement in achievements:
            is_earned = bool(achievement.get("earned"))
            color = TEAL if is_earned else MUTED
            title = str(achievement.get("name", "A deed on the road"))
            details = str(achievement.get("description", ""))
            inner_width = max(40, width - 32)
            height = 52 + len(_wrap(title, self.bold_font, inner_width)) * self.line_height
            if details:
                height += len(_wrap(details, self.font, inner_width)) * self.line_height + 6
            self.pg.draw.rect(screen, CARD, (x, y, width, height))
            self.pg.draw.rect(screen, EDGE, (x, y, width, height), 1)
            self.pg.draw.rect(screen, color, (x, y, 3, height))
            self._text(screen, "EARNED" if is_earned else "UNDISCOVERED", x + 16, y + 11, color, font=self.small_font)
            bottom = self._paragraph(screen, title, x + 16, y + 33, inner_width, PARCHMENT, font=self.bold_font)
            if details:
                self._paragraph(screen, details, x + 16, bottom + 6, inner_width)
            y += height + 12
        return y - start_y + 8

    def _draw_information(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        for section in self.data.get("sections", []):
            if isinstance(section, dict):
                heading = str(section.get("heading", ""))
                prose = str(section.get("text", ""))
            else:
                heading, prose = "", str(section)
            if heading:
                y = self._paragraph(screen, heading, x, y, width, AMBER, font=self.bold_font) + 8
            if prose:
                y = self._paragraph(screen, prose, x, y, width, PARCHMENT) + 24
        return y - start_y + 8

    def _slot_action(self) -> dict[str, Any] | None:
        slots = self.data.get("slots", [])
        if not slots or not 0 <= self.selected < len(slots):
            return None
        slot = slots[self.selected]
        if self.data.get("mode") == "load" and (slot.get("empty", False) or slot.get("corrupt", False)):
            return None
        return {"action": "select_slot", "slot": slot.get("slot", slot.get("id", self.selected + 1))}

    def _draw_saves(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        mode = self.data.get("mode", "save")
        slots = self.data.get("slots", [])
        if not slots:
            return self._paragraph(screen, "There are no campfire memories yet.", x + 18, y + 20, width - 36) - start_y + 25
        self.selected = max(0, min(self.selected, len(slots) - 1))
        text_width = max(80, width - 210) if width >= 500 else width - 32
        card_heights = []
        for slot in slots:
            title = "Damaged memory" if slot.get("corrupt", False) else "Empty campfire" if slot.get("empty", False) else slot.get("name", "Traveler")
            card_heights.append(max(109, 73 + len(_wrap(title, self.bold_font, text_width)) * self.line_height) + (42 if width < 500 else 0))
        if self._ensure_selection:
            top = sum(height + 12 for height in card_heights[:self.selected])
            bottom = top + card_heights[self.selected]
            previous_scroll = self.scroll
            if top < self.scroll:
                self.scroll = top
            elif bottom > self.scroll + self.content_rect.height:
                self.scroll = bottom - self.content_rect.height
            y += previous_scroll - self.scroll
            start_y = y
            self._ensure_selection = False
        for index, (slot, height) in enumerate(zip(slots, card_heights)):
            empty = slot.get("empty", False)
            corrupt = slot.get("corrupt", False)
            title = "Damaged memory" if corrupt else "Empty campfire" if empty else slot.get("name", "Traveler")
            card = self.pg.Rect(x, y, width, height)
            self.pg.draw.rect(screen, (40, 51, 52) if index == self.selected else CARD, card)
            self.pg.draw.rect(screen, RED if corrupt else AMBER if index == self.selected else EDGE, card, 1)
            label = f"CAMP {slot.get('slot', slot.get('id', index + 1))}"
            self._text(screen, label, x + 16, y + 11, AMBER, font=self.small_font)
            bottom = self._paragraph(screen, title, x + 16, y + 33, text_width, RED if corrupt else MUTED if empty else PARCHMENT, font=self.bold_font)
            if corrupt:
                detail = "Cannot be loaded." if mode == "load" else "Replace this damaged memory."
                self._paragraph(screen, detail, x + 16, bottom + 7, text_width, MUTED, font=self.small_font)
            elif not empty:
                minutes = max(0, _number(slot.get("play_minutes", 0)))
                detail = f"Chapter {slot.get('chapter', '?')}  /  {minutes // 60}h {minutes % 60:02d}m"
                self._paragraph(screen, detail, x + 16, bottom + 7, text_width, MUTED, font=self.small_font)
            elif mode == "save":
                self._text(screen, "A place for your journey", x + 16, bottom + 7, MUTED, font=self.small_font)
            button_label = "Load memory" if mode == "load" else "Save here" if empty else "Overwrite..."
            button = self.pg.Rect(x + width - 164, y + (height - 37) // 2, 148, 37) if width >= 500 else self.pg.Rect(x + 16, y + height - 47, min(180, width - 32), 35)
            visible = card.clip(self.content_rect)
            if visible.width and visible.height:
                self.hit_targets.append((visible, "slot", index))
            enabled = not (mode == "load" and (empty or corrupt))
            self._button(screen, button, button_label if enabled else "Unavailable", "slot_action", index, primary=index == self.selected, enabled=enabled)
            y += height + 12
        return y - start_y
