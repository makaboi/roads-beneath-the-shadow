"""Read-only, main-thread adventure panels for the pixel presentation.

The story worker supplies plain snapshots.  This module never imports pygame,
reads game state, or changes a character: it returns explicit actions for the
engine to validate.  Closing a panel leaves the caller's story page intact.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .pixel_theme import (
    AMBER, CARD, EDGE, INK, MUTED, PANEL, PARCHMENT, RED, SELECTED, STEEL, TEAL,
    ORIGIN_PORTRAIT_FILE, ORIGIN_PORTRAIT_SIZE, draw_medallion, draw_pixel_frame,
    load_font, origin_face_rect,
)
from .pixel_world import origin_portrait_rect


_TITLES = {
    "inventory": ("THE TRAVELER'S PACK", "Equipment, provisions, and things worth keeping"),
    "character": ("THE TRAVELER", "A life shaped by the road"),
    "journal": ("THE ROAD JOURNAL", "Promises to keep. Clues to remember."),
    "map": ("ROADS REMEMBERED", "Your journey through the shadow"),
    "saves": ("CAMPFIRE MEMORIES", "Keep a place on the road"),
    "chronicle": ("THE TRAVELER'S CHRONICLE", "The roads you finished and the deeds remembered"),
    "information": ("NOTES FROM THE ROAD", "Read closely, then return to your journey"),
    "background": ("WHO WALKS THIS ROAD?", "Left / Right or click: compare. Enter: choose."),
}
_TABS = {
    "inventory": (("All items", "all"), ("Equipment", "gear"), ("Supplies", "supplies"), ("Keepsakes", "quest")),
    "journal": (("Active quests", "active"), ("Completed", "completed"), ("Clues", "clues"), ("This stop", "decision")),
    "map": (("This stop", "here"), ("Remembered roads", "route")),
    "chronicle": (("Overview", "all"), ("Earned", "earned"), ("Still to discover", "open")),
}
_ICONS = {
    "weapon": ("..........aa", ".........aa.", "........aa..", ".......aa...", "......aa....", ".....aa.....", "..a.aa......", "...aaa......", "...aaa......", "..aa..a.....", ".aa.........", "............"),
    "armor": ("..aaaaaa....", ".aaaaaaaa...", ".aa....aa...", ".aa....aa...", ".aaa..aaa...", "..aaaaaa....", "..aaaaaa....", "...aaaa.....", "....aa......", "............", "............", "............"),
    "consumable": ("............", ".....aa.....", ".....aaa....", "..aa..aa....", "..aaa.a.....", "...aaaa.....", ".....a.aaa..", ".....aaaaa..", ".....a..a...", "....aa......", "...aa.......", "............"),
    "quest": (".....a......", "..a..a..a...", "...aaa.a....", "....aaa.....", "aaaaaaaaaaa.", "....aaa.....", "...a.aaa....", "..a..a..a...", ".....a......", "............", "............", "............"),
}

# Small material-colored silhouettes make a staff, letter, or flask distinct
# at the same 24-pixel footprint. They describe objects, never their mechanics.
_ITEM_ICONS = {
    "ash_staff": ("..........w.", ".........wh.", "........wh..", ".......wh...", "......wh....", ".....wh.....", "....wh......", "...wh.......", "..wh........", ".wh.........", ".w..........", "............"),
    "hunting_knife": ("............", ".........h..", "........hh..", ".......hh...", "......hh....", ".....hh.....", "....hh......", "...aaa......", "....a.......", "..ww........", ".ww.........", "............"),
    "bree_blade": ("..........h.", ".........hh.", "........hh..", ".......hh...", "......hh....", ".....hh.....", "..a.hh......", "...aha......", "...aaa......", "..ww..a.....", ".ww.........", "............"),
    "numenorean_blade": (".........h..", "........hh..", ".......hhh..", "......hhh...", ".....hhh....", ".....hh.....", "..a.hh......", "...aha......", "...aaa......", "..ww..a.....", ".ww.........", "............"),
    "orc_cleaver": (".......hhh..", "......hhdd..", ".....hhddd..", "....hhddd...", "...hhddd....", "....hdd.....", ".....d......", "....a.......", "...ww.......", "..ww........", ".ww.........", "............"),
    "patched_leather": ("..ww....ww..", ".wwww..wwww.", ".wwwwwwwwww.", "..wwwaawww..", "..wwwahwww..", "..wwwaawww..", "..wwwwwwww..", "..waawwwww..", "..wahwwwww..", "..waawwwww..", "..wwwwwwww..", "............"),
    "ranger_cloak": ("....tttt....", "...ttddtt...", "...tddddt...", "..tttddttt..", "..tttttttt..", ".ttttattttt.", ".tttthttttt.", ".tttttttttt.", "tttttddttttt", "ttttddddtttt", ".ttddddddtt.", "............"),
    "healing_herb": (".....h......", "....htt.....", ".ht..tt.....", ".htt.t..th..", "..tt.t.tth..", "...tttttt...", ".....tt.....", "..ht.t......", "..httth.....", "....aa......", "...aaa......", "............"),
    "smoke_bomb": ("....hhhh....", "....wwww....", ".....ww.....", "....waaw....", "...waaaaw...", "..waaaaaaw..", "..waaaahaw..", "..waaaahaw..", "..waaaaaww..", "...wwwwww...", "............", "............"),
    "lembas_scrap": ("............", "...tttttt...", "..ttpppptt..", ".ttppapaptt.", ".tppppppppt.", ".tppapapapt.", ".ttpppppptt.", "..ttaatttt..", "...taatt....", "....tttt....", "............", "............"),
    "sealed_letter": ("............", ".pppppppppp.", ".phpppppphp.", ".pphpppphpp.", ".ppphpphppp.", ".pppprrpppp.", ".pppprrpppp.", ".pphpppphpp.", ".phpppppphp.", ".pppppppppp.", "............", "............"),
    "calenor_map": (".wwwwwwwwww.", ".pppppppppw.", ".pptttppppw.", ".pppptpphpw.", ".pppptphppw.", ".ppptphpppw.", ".ppptpppppw.", ".ppppttpppw.", ".ppppptpppw.", ".pppppppppw.", ".wwwwwwwwww.", "............"),
    "star_key": (".....h......", "..h..h..h...", "...h.h.h....", "....hhh.....", "hhhhhahhhhh.", "....hhh.....", "...h.h.h....", "..h..h..h...", ".....h......", "............", "............", "............"),
    "silver_star": (".....h......", "..h..h......", "...h.h......", "....hhh.....", "hhhhhahhhhh.", "....hhh.....", "...h.h.h....", "..h..h..h...", ".....h......", "............", "............", "............"),
    "ranger_token": ("............", ".....tt.....", "...tthtt....", "..ttthtttt..", ".tttthttt...", ".tttthtt....", "..ttthttt...", "...tthtttt..", "....thtt....", ".....h......", ".....w......", "............"),
    "black_arrowhead": (".....h......", "....hdd.....", "....hddd....", "...hddddd...", "..hddrdddd..", ".hddrrrdddd.", ".ddddrddddd.", "..dddhdddd..", "....dhdd....", ".....h......", "............", "............"),
    "watch_badge": ("..aaaaaaa...", ".aapppppaa..", ".apppapppa..", ".appaaappa..", ".apppapppa..", "..apppppa...", "..aapppaa...", "...aaaaa....", "....aaa.....", ".....a......", "............", "............"),
    "calenor_broken_sword": ("............", "......hh....", ".....hdd....", "....hd......", "...hd.......", "..hd........", "...aaa......", "....a.......", "..ww........", ".ww.........", "............", "............"),
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
    ``item_id``, saves ``select_slot`` with ``slot``, or ``choose_origin`` with
    ``origin_id``. An action never edits
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
        self.detail_body_rect = pg.Rect(0, 0, 0, 0)
        self._inventory_memory: dict[str, Any] | None = None
        self._scrollbars: dict[str, tuple[Any, Any, int]] = {}
        self._dragging: tuple[str, int] | None = None
        self._ensure_selection = True
        self._font_size = 0
        self._portraits: dict[tuple[Any, int], Any] = {}
        self._fonts(16)

    def _fonts(self, size: int) -> None:
        if self._font_size == size:
            return
        self._font_size = size
        self.font = load_font(self.pg, size)
        self.small_font = load_font(self.pg, max(11, size - 3))
        self.bold_font = load_font(self.pg, size, bold=True)
        self.title_font = load_font(self.pg, size + 8, bold=True)
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
        self._scrollbars = {}
        self._dragging = None
        self._ensure_selection = True
        memory = self._inventory_memory
        if kind == "inventory" and memory and data.get("journey_id") and memory["journey_id"] == data["journey_id"]:
            self.tab_index = memory["tab_index"]
            items = self.visible_items()
            self.selected = next((index for index, item in enumerate(items) if item.get("id") == memory["item_id"]), min(memory["selected"], max(0, len(items) - 1)))
            self.scroll = memory["scroll"]
            self.detail_scroll = memory["detail_scroll"] if items and items[self.selected].get("id") == memory["item_id"] else 0

    def close(self) -> None:
        if self.active and self.kind == "inventory" and self.data.get("journey_id"):
            item = self._selected_item()
            self._inventory_memory = {
                "journey_id": self.data["journey_id"], "tab_index": self.tab_index,
                "item_id": item.get("id") if item else None, "selected": self.selected,
                "scroll": self.scroll, "detail_scroll": self.detail_scroll,
            }
        self.active = False
        self.hit_targets = []
        self._dragging = None

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
            character = self.data.get("character", self.data)
            if _number(character.get("max_hp")) > 0 and _number(character.get("hp")) >= _number(character["max_hp"]):
                return None
            return {"action": "use", "item_id": item["id"]}
        return None

    def _recovery_amount(self, item: dict[str, Any]) -> int:
        character = self.data.get("character", self.data)
        capacity = _number(item.get("healing_effective", item.get("healing")))
        if "healing_effective" not in item and character.get("origin") == "healers_apprentice":
            capacity += 2
        if _number(character.get("max_hp")) > 0:
            return min(capacity, max(0, _number(character["max_hp"]) - _number(character.get("hp"))))
        return capacity

    def _equipment_difference(self, item: dict[str, Any]) -> tuple[int, str]:
        key, label = ("attack", "attack") if item.get("slot") == "weapon" else ("defense", "armor")
        if f"{key}_delta" in item:
            return _number(item[f"{key}_delta"]), label
        equipped = next((other for other in self.data.get("items", []) if isinstance(other, dict) and other.get("slot") == item.get("slot") and other.get("equipped")), None)
        character = self.data.get("character", self.data)
        baseline = _number(equipped.get(key)) if equipped else _number(character.get("weapon_attack" if key == "attack" else "armor_defense"))
        return _number(item.get(key)) - baseline, label

    def _change_tab(self, direction: int) -> None:
        tabs = _TABS.get(self.kind, ())
        if tabs:
            self.tab_index = (self.tab_index + direction) % len(tabs)
            self.selected = self.scroll = self.detail_scroll = 0
            self._ensure_selection = True

    def _move_selection(self, direction: int) -> None:
        entries = self.visible_items() if self.kind == "inventory" else self.data.get("origins" if self.kind == "background" else "slots", [])
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
        if event.type == getattr(pg, "WINDOWFOCUSLOST", -1):
            self._dragging = None
            return False, None
        if event.type in {pg.QUIT, pg.VIDEORESIZE, getattr(pg, "WINDOWRESIZED", -1)}:
            return False, None
        if event.type == pg.KEYDOWN:
            key = event.key
            if key == pg.K_F11:
                return False, None
            if key == pg.K_ESCAPE:
                self.close()
                return True, {"action": "close"}
            if self.kind == "background" and key in {pg.K_1, pg.K_2, pg.K_3}:
                self._choose_background_index(key - pg.K_1)
                return True, None
            if key == pg.K_TAB:
                direction = -1 if getattr(event, "mod", 0) & pg.KMOD_SHIFT else 1
                if self.kind == "background":
                    self._cycle_background(direction)
                else:
                    self._change_tab(direction)
            elif key in {pg.K_LEFT, pg.K_RIGHT}:
                direction = -1 if key == pg.K_LEFT else 1
                if self.kind == "background":
                    self._cycle_background(direction)
                else:
                    self._change_tab(direction)
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
                if self.kind == "background":
                    return True, self._background_action()
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
                    elif target == "origin":
                        self._choose_background_index(value)
                    elif target == "origin_action":
                        return True, self._background_action()
                    elif target == "scrollbar":
                        track, thumb, _ = self._scrollbars[value]
                        grab = event.pos[1] - thumb.top if thumb.collidepoint(event.pos) else thumb.height // 2
                        self._dragging = (value, grab)
                        self._drag_scrollbar(event.pos[1])
                    break
            return True, None
        if event.type == pg.MOUSEMOTION and self._dragging:
            self._drag_scrollbar(event.pos[1])
            return True, None
        if event.type == pg.MOUSEBUTTONUP:
            if getattr(event, "button", None) == 1:
                self._dragging = None
            return True, None
        # A modal consumes pointer/text events so they cannot select a story
        # choice behind it. Window lifecycle events still belong to the caller.
        return event.type in {pg.MOUSEMOTION, pg.MOUSEBUTTONUP, pg.KEYUP, pg.TEXTINPUT, pg.TEXTEDITING}, None

    def _drag_scrollbar(self, pointer_y: int) -> None:
        if not self._dragging:
            return
        key, grab = self._dragging
        if key not in self._scrollbars:
            self._dragging = None
            return
        track, thumb, maximum = self._scrollbars[key]
        travel = max(1, track.height - thumb.height)
        value = round(maximum * max(0, min(travel, pointer_y - grab - track.top)) / travel)
        if key == "detail":
            self.detail_scroll = value
        else:
            self.scroll = value
        self._ensure_selection = False

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
        pattern = _ITEM_ICONS.get(kind, _ICONS.get(kind, _ICONS["quest"]))
        palette = {"a": color, "h": STEEL, "p": PARCHMENT, "t": TEAL,
                   "r": RED, "w": (163, 122, 78), "d": EDGE}
        for row, pixels in enumerate(pattern):
            for column, pixel in enumerate(pixels):
                if pixel in palette:
                    self.pg.draw.rect(screen, palette[pixel], (x + column * scale, y + row * scale, scale, scale))

    def _item_icon(self, screen: Any, item: dict[str, Any], x: int, y: int, scale: int = 2) -> None:
        """Keep the thumbnail and the inspected object visually identical."""
        kind = str(item.get("kind", "quest"))
        key = str(item.get("id", ""))
        if key not in _ITEM_ICONS:
            key = kind
        size = 12 * scale
        self.pg.draw.rect(screen, INK, (x - 3, y - 3, size + 6, size + 6))
        color = TEAL if kind in {"armor", "consumable"} else AMBER
        self._icon(screen, key, x, y, color, scale)

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

    def _companion_portrait(self, screen: Any, name: Any, x: int, y: int) -> bool:
        """Reuse the authored companion identity at the existing 40×48 bounds."""
        name = str(name).casefold()
        index = {"mara": 3, "tobin": 4, "calenor": 5}.get(name)
        if index is None:
            return False
        key = (f"companion:{name}", 1)
        if key not in self._portraits:
            try:
                atlas = self.pg.image.load(str(Path(__file__).with_name("pixel_assets") / "world-battle-cast.png"))
                if atlas.get_size() != (120, 96):
                    raise ValueError("Companion portrait sheet has unexpected dimensions")
                crop = self.pg.Rect((index % 3) * 40, (index // 3) * 48, 40, 48)
                self._portraits[key] = atlas.subsurface(crop).copy()
            except (OSError, ValueError, self.pg.error):
                self._portraits[key] = None
        portrait = self._portraits[key]
        if portrait is None:
            return self._portrait(screen, {"mara": 4, "tobin": 5, "calenor": 6}[name], x, y, 2)
        screen.blit(portrait, (x, y))
        return True

    def _origin_portrait(self, screen: Any, origin: Any, x: int, y: int, scale: int = 4) -> bool:
        """Keep the chosen background visible in the character sheet."""
        crop = origin_portrait_rect(str(origin or ""))
        if crop is None:
            return self._portrait(screen, 0, x, y, scale)
        key = (f"origin:{crop[0]}", scale)
        if key not in self._portraits:
            try:
                atlas = self.pg.image.load(str(Path(__file__).with_name("pixel_assets") / "world-portraits.png"))
                frame = atlas.subsurface(self.pg.Rect(crop))
                self._portraits[key] = self.pg.transform.scale(frame, (20 * scale, 24 * scale))
            except (OSError, ValueError, self.pg.error):
                self._portraits[key] = None
        portrait = self._portraits[key]
        if portrait is None:
            return self._portrait(screen, 0, x, y, scale)
        screen.blit(portrait, (x, y))
        return True

    def _identity_portrait(self, screen: Any, origin: Any, rect: Any) -> bool:
        """Center a crisp face, with the world sprite as a damaged-install fallback."""
        rect = self.pg.Rect(rect)
        crop = origin_face_rect(str(origin or ""))
        face_width, face_height = ORIGIN_PORTRAIT_SIZE
        scale = min(rect.width // face_width, rect.height // face_height)
        if crop is not None and scale > 0:
            key = (f"face:{crop[0]}", scale)
            if key not in self._portraits:
                try:
                    atlas = self.pg.image.load(str(ORIGIN_PORTRAIT_FILE))
                    if atlas.get_size() != (face_width * 3, face_height):
                        raise ValueError("Origin portrait sheet has unexpected dimensions")
                    frame = atlas.subsurface(self.pg.Rect(crop))
                    self._portraits[key] = self.pg.transform.scale(frame, (face_width * scale, face_height * scale))
                except (OSError, ValueError, self.pg.error):
                    self._portraits[key] = None
            portrait = self._portraits[key]
            if portrait is not None:
                screen.blit(portrait, portrait.get_rect(center=rect.center))
                return True
        sprite_scale = min(rect.width // 20, rect.height // 24)
        if sprite_scale > 0:
            x = rect.centerx - 20 * sprite_scale // 2
            y = rect.centery - 24 * sprite_scale // 2
            return self._origin_portrait(screen, origin, x, y, sprite_scale)
        return False

    def _button_font(self, label: str, rect: Any) -> Any:
        """Keep complete captions inside their controls at enlarged text sizes."""
        for font in (self.bold_font, self.small_font):
            if font.size(label)[0] <= rect.width - 12 and font.get_linesize() <= rect.height - 6:
                return font
        size = max(11, self._font_size - 4)
        font = load_font(self.pg, size, bold=True)
        while size > 11 and (font.size(label)[0] > rect.width - 12 or font.get_linesize() > rect.height - 6):
            size -= 1
            font = load_font(self.pg, size, bold=True)
        return font

    def _button(self, screen: Any, rect: Any, label: str, target: str, value: Any = None, *, primary: bool = False, enabled: bool = True) -> None:
        pg = self.pg
        draw_pixel_frame(pg, screen, rect, fill=INK if not enabled else (47, 58, 57) if primary else CARD,
                         edge=AMBER if primary and enabled else EDGE)
        text = self._button_font(label, rect).render(label, False, PARCHMENT if primary and enabled else MUTED)
        screen.blit(text, text.get_rect(center=rect.center))
        clip = screen.get_clip()
        visible = rect.clip(clip)
        if enabled and visible.width and visible.height:
            self.hit_targets.append((visible, target, value))

    def _scrollbar(self, screen: Any, rect: Any, offset: int, maximum: int, *, key: str = "main") -> None:
        if maximum <= 0 or rect.height < 20:
            return
        track = self.pg.Rect(rect.right - 5, rect.top + 2, 3, rect.height - 4)
        self.pg.draw.rect(screen, EDGE, track)
        height = min(track.height, max(24, int(track.height * rect.height / (rect.height + maximum))))
        top = track.top + int((track.height - height) * min(offset, maximum) / maximum)
        thumb = self.pg.Rect(track.left, top, 3, height)
        self.pg.draw.rect(screen, AMBER, thumb)
        # Give the thin pixel rail a forgiving pointer target.
        hit = self.pg.Rect(track.left - 4, track.top, 11, track.height)
        self._scrollbars[key] = (track, thumb, maximum)
        self.hit_targets.append((hit, "scrollbar", key))

    def draw(self, screen: Any, rect: Any, *, text_size: str = "standard") -> None:
        if not self.active:
            return
        pg = self.pg
        rect = pg.Rect(rect)
        if rect.width < 260 or rect.height < 220:
            return
        preference = {"standard": 0, "large": 3, "larger": 6}.get(text_size, 0)
        self._fonts((14 if rect.width < 900 else 18 if rect.width >= 1400 else 16) + preference)
        old_clip = screen.get_clip()
        screen.set_clip(rect)
        screen.fill(INK, rect)
        frame = rect.inflate(-max(16, min(56, rect.width // 20)), -28)
        # A journal page remains a readable page on a wide monitor. Keep
        # equipment columns and their actions together rather than stretching
        # every sentence and pointer journey across the entire display.
        if frame.width > 1180:
            frame.width = 1180
            frame.centerx = rect.centerx
        draw_pixel_frame(pg, screen, frame, ornate=True)
        self.hit_targets = []
        self._scrollbars = {}
        padding = 22 if rect.width >= 700 else 14
        left, width = frame.left + padding, frame.width - padding * 2
        title, subtitle = _TITLES[self.kind]
        if self.kind == "information":
            title = str(self.data.get("title", title))
            subtitle = str(self.data.get("subtitle", subtitle))
        elif self.kind == "saves":
            subtitle = "Choose the road you want to continue" if self.data.get("mode") == "load" else "Choose a campfire to remember this journey"
        title_y = frame.top + 20
        draw_medallion(pg, screen, (left + 13, title_y + 14), radius=14)
        title_bottom = self._paragraph(screen, title, left + 38, title_y, width - 38, PARCHMENT, font=self.title_font)
        subtitle_bottom = self._paragraph(screen, subtitle, left, title_bottom + 5, width, MUTED, font=self.small_font)
        return_label = "Return to the main menu  [Esc]" if self.kind in {"chronicle", "background"} else "Return to the road  [Esc]"
        if self.kind in {"information", "saves"}:
            return_label = str(self.data.get("return_label", "Back  [Esc]"))
        if self.kind == "background" and width < 500:
            return_label = "Back [Esc]"
        button_width = min(width, self.bold_font.size(return_label)[0] + 26)
        footer_height = 72 if width < 600 or preference else 60
        notice = str(self.data.get("notice") or "").strip() if self.kind == "inventory" else ""
        notice_width = width - button_width - 20
        if notice and notice_width >= 180:
            notice_height = len(_wrap(notice, self.small_font, notice_width)) * (self.small_font.get_linesize() + 3)
            footer_height = max(footer_height, notice_height + 20)
        footer_y = frame.bottom - footer_height
        pg.draw.line(screen, EDGE, (left, footer_y), (left + width, footer_y))
        self._button(screen, pg.Rect(left + width - button_width, footer_y + 12, button_width, 34), return_label, "close")
        hint = "Tab: categories   Arrows: browse"
        if self.kind == "inventory":
            hint = "Enter: equip / use   Shift+PgDn: details"
        elif self.kind == "saves":
            hint = "Arrows: choose   Enter: select"
        elif self.kind == "background":
            hint = "Left / Right: compare   Enter: choose"
        elif self.kind in {"journal", "map", "chronicle"}:
            hint = "Tab: sections   Scroll: read"
        elif self.kind not in _TABS:
            hint = "Scroll to read   Enter: return"
        if notice and notice_width >= 180:
            notice_bottom = self._paragraph(screen, notice, left, footer_y + 9, notice_width, TEAL, font=self.small_font)
            if notice_bottom + self.small_font.get_linesize() + 4 < frame.bottom and self.small_font.size(hint)[0] <= notice_width:
                self._text(screen, hint, left, notice_bottom + 3, MUTED, font=self.small_font)
        elif self.kind == "background":
            action_space = width - button_width - 14
            choose_label = "Choose background [Enter]" if self.bold_font.size("Choose background [Enter]")[0] + 26 <= action_space else "Choose [Enter]"
            action_width = min(action_space, self.bold_font.size(choose_label)[0] + 26)
            self._button(screen, pg.Rect(left, footer_y + 12, max(1, action_width), 34), choose_label, "origin_action", primary=True, enabled=bool(self.data.get("origins")))
            if footer_height > 60:
                self._text(screen, "Scroll / PgDn: read background", left, footer_y + 51, MUTED, font=self.small_font)
        elif width > button_width + self.small_font.size(hint)[0] + 20:
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
        self.detail_body_rect = pg.Rect(0, 0, 0, 0)
        if self.kind == "inventory":
            self._draw_inventory(screen)
        elif self.kind == "background":
            previous_scroll = self.scroll
            self._draw_background(screen)
            if self.scroll != previous_scroll:
                screen.set_clip(self.content_rect)
                screen.fill(PANEL, self.content_rect)
                self.hit_targets = [target for target in self.hit_targets if not self.content_rect.colliderect(target[0])]
                self._draw_background(screen)
        else:
            screen.set_clip(self.content_rect.clip(rect))
            render = {
                "character": self._draw_character, "journal": self._draw_journal,
                "map": self._draw_map, "saves": self._draw_saves,
                "chronicle": self._draw_chronicle, "information": self._draw_information,
            }[self.kind]
            height = render(screen, self.content_rect.left, self.content_rect.top - self.scroll, self.content_rect.width - 12)
            self.max_scroll = max(0, height - self.content_rect.height)
            clamped_scroll = min(self.scroll, self.max_scroll)
            if clamped_scroll != self.scroll:
                # Reflow can shorten a long journal or archive. Draw its
                # reachable position immediately, including matching pointer
                # targets, instead of showing an empty frame after resizing.
                self.scroll = clamped_scroll
                screen.fill(PANEL, self.content_rect)
                self.hit_targets = [target for target in self.hit_targets if not self.content_rect.colliderect(target[0])]
                render(screen, self.content_rect.left, self.content_rect.top - self.scroll, self.content_rect.width - 12)
            screen.set_clip(rect)
            self._scrollbar(screen, self.content_rect, self.scroll, self.max_scroll)
        screen.set_clip(old_clip)

    def _choose_background_index(self, index: int) -> None:
        origins = self.data.get("origins", [])
        if origins:
            self.selected = max(0, min(index, len(origins) - 1))
            self.scroll = 0

    def _cycle_background(self, direction: int) -> None:
        origins = self.data.get("origins", [])
        if origins:
            self._choose_background_index((self.selected + direction) % len(origins))

    def _background_action(self) -> dict[str, Any] | None:
        origins = self.data.get("origins", [])
        if not origins or not 0 <= self.selected < len(origins):
            return None
        origin = origins[self.selected]
        if not isinstance(origin, dict) or not origin.get("id"):
            return None
        return {"action": "choose_origin", "origin_id": origin["id"]}

    def _draw_background(self, screen: Any) -> None:
        """Compare identity and attributes, then inspect the selected life."""
        pg = self.pg
        region = self.content_rect
        origins = self.data.get("origins", [])
        if not origins:
            self._paragraph(screen, "No backgrounds are available.", region.left, region.top, region.width)
            return
        self.selected = max(0, min(self.selected, len(origins) - 1))
        if self._font_size > 16 and region.height < 440:
            self._draw_background_compact(screen)
            return
        screen.set_clip(region)
        columns = len(origins) if region.width >= 540 else 1
        gap = 12
        card_width = (region.width - gap * (columns - 1) - 10) // columns
        rows = list(enumerate(origins)) if columns > 1 else [(self.selected, origins[self.selected])]
        top = region.top
        if columns == 1:
            selector_width = (region.width - 10) // len(origins)
            for index in range(len(origins)):
                self._button(screen, pg.Rect(region.left + selector_width * index, top, selector_width - 6, 28), str(index + 1), "origin", index, primary=index == self.selected)
            top += 37
        portrait_width, portrait_height = ORIGIN_PORTRAIT_SIZE
        header_width = card_width - portrait_width - 36
        header_height = max(portrait_height, max(len(_wrap(origin.get("name", "Traveler"), self.bold_font, header_width)) * self.line_height for _, origin in rows))
        ability_height = max(len(_wrap(origin.get("ability_name", ""), self.small_font, card_width - 24)) * (self.small_font.get_linesize() + 3) for _, origin in rows)
        card_height = header_height + self.line_height * 2 + ability_height + 37
        for column, (index, origin) in enumerate(rows):
            card = pg.Rect(region.left + column * (card_width + gap), top, card_width, card_height)
            draw_pixel_frame(pg, screen, card, fill=SELECTED if index == self.selected else CARD,
                             edge=AMBER if index == self.selected else EDGE)
            self._identity_portrait(screen, origin.get("id"), pg.Rect(card.left + 12, card.top + 12, portrait_width, portrait_height))
            self._paragraph(screen, origin.get("name", "Traveler"), card.left + portrait_width + 23, card.top + 12, header_width, PARCHMENT, font=self.bold_font)
            text_y = card.top + header_height + 20
            self._text(screen, f"Health {origin.get('max_hp', '?')}", card.left + 12, text_y, RED, font=self.small_font)
            text_y += self.line_height
            attributes = f"STR {origin.get('strength', '?')}  CUN {origin.get('cunning', '?')}  WILL {origin.get('will', '?')}"
            self._text(screen, attributes, card.left + 12, text_y, MUTED, font=self.small_font)
            self._paragraph(screen, origin.get("ability_name", ""), card.left + 12, text_y + self.line_height, card.width - 24, TEAL, font=self.small_font)
            visible = card.clip(region)
            if visible.width and visible.height:
                self.hit_targets.append((visible, "origin", index))
        body = pg.Rect(region.left, top + card_height + 15, region.width, max(1, region.bottom - top - card_height - 15))
        self.detail_rect = self.detail_body_rect = body
        screen.set_clip(body)
        origin = origins[self.selected]
        x, width = body.left + 4, body.width - 18
        start_y = body.top - self.scroll
        y = self._draw_background_details(screen, origin, x, start_y, width)
        self.max_scroll = max(0, y - start_y + 8 - body.height)
        self.scroll = min(self.scroll, self.max_scroll)
        screen.set_clip(region)
        self._scrollbar(screen, body, self.scroll, self.max_scroll)

    def _draw_background_compact(self, screen: Any) -> None:
        """Keep enlarged origin prose scrollable above the fixed choice dock."""
        pg = self.pg
        region = self.content_rect
        origins = self.data["origins"]
        screen.set_clip(region)
        selector_width = (region.width - 10) // len(origins)
        short_names = {"bree_wayfarer": "Wayfarer", "north_road_scout": "Scout", "healers_apprentice": "Healer"}
        selector_height = max(30, self.bold_font.get_linesize() + 8)
        for index, origin in enumerate(origins):
            label = f"{index + 1} {short_names.get(origin.get('id'), '')}".strip()
            self._button(screen, pg.Rect(region.left + selector_width * index, region.top, selector_width - 6, selector_height), label, "origin", index, primary=index == self.selected)
        body = pg.Rect(region.left, region.top + selector_height + 12, region.width, max(1, region.height - selector_height - 12))
        self.detail_rect = self.detail_body_rect = body
        screen.set_clip(body)
        origin = origins[self.selected]
        x, width = body.left + 4, body.width - 18
        start_y = body.top - self.scroll
        portrait_width, portrait_height = ORIGIN_PORTRAIT_SIZE
        header_width = width - portrait_width - 36
        header_height = max(portrait_height, len(_wrap(origin.get("name", "Traveler"), self.bold_font, header_width)) * self.line_height)
        stats = f"Health {origin.get('max_hp', '?')}  /  STR {origin.get('strength', '?')}  CUN {origin.get('cunning', '?')}  WILL {origin.get('will', '?')}"
        card_height = header_height + 32 + len(_wrap(stats, self.small_font, width - 24)) * (self.small_font.get_linesize() + 3)
        card = pg.Rect(x, start_y, width, card_height)
        draw_pixel_frame(pg, screen, card, fill=CARD, edge=AMBER)
        self._identity_portrait(screen, origin.get("id"), pg.Rect(x + 12, start_y + 12, portrait_width, portrait_height))
        self._paragraph(screen, origin.get("name", "Traveler"), x + portrait_width + 23, start_y + 12, header_width, PARCHMENT, font=self.bold_font)
        self._paragraph(screen, stats, x + 12, start_y + header_height + 20, width - 24, TEAL, font=self.small_font)
        y = self._draw_background_details(screen, origin, x, start_y + card_height + 17, width)
        self.max_scroll = max(0, y - start_y + 8 - body.height)
        self.scroll = min(self.scroll, self.max_scroll)
        screen.set_clip(region)
        self._scrollbar(screen, body, self.scroll, self.max_scroll)

    def _draw_background_details(self, screen: Any, origin: dict[str, Any], x: int, y: int, width: int) -> int:
        y = self._paragraph(screen, origin.get("description", ""), x, y, width, PARCHMENT) + 16
        y = self._paragraph(screen, origin.get("ability_name", ""), x, y, width, TEAL, font=self.bold_font) + 5
        if origin.get("ability_rules"):
            y = self._paragraph(screen, origin["ability_rules"], x, y, width, AMBER, font=self.small_font) + 5
        y = self._paragraph(screen, origin.get("ability_description", ""), x, y, width) + 17
        y = self._section(screen, "Starting pack", x, y, width)
        for item in origin.get("starting_items", []):
            y = self._paragraph(screen, str(item), x, y, width, PARCHMENT) + 4
        y += 12
        y = self._paragraph(screen, f"Weapon: {origin.get('weapon_name', 'Unarmed')}   Armor: {origin.get('armor_name', 'Travel clothes')}", x, y, width) + 18
        y = self._paragraph(screen, "Strength adds to strikes and counters. Cunning helps Flanking Strike and escape attempts. Will strengthens Field Remedy.", x, y, width, MUTED, font=self.small_font)
        return y

    def _draw_inventory(self, screen: Any) -> None:
        pg = self.pg
        region = self.content_rect
        gap = 20 if region.width >= 700 else 12
        left_width = max(100, (region.width - gap) * 46 // 100)
        pack_rect = pg.Rect(region.left, region.top, left_width, region.height)
        self.detail_rect = pg.Rect(pack_rect.right + gap, region.top, region.width - left_width - gap, region.height)
        items = self.visible_items()
        self.selected = min(self.selected, max(0, len(items) - 1))
        card_heights = []
        for item in items:
            markers = self._item_markers(item)
            name_height = len(_wrap(item.get("name", "Unnamed item"), self.bold_font, left_width - 68)) * self.line_height
            marker_height = len(_wrap(markers, self.small_font, left_width - 68)) * (self.small_font.get_linesize() + 3)
            card_heights.append(max(82, name_height + marker_height + 30))
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
                draw_pixel_frame(pg, screen, card, fill=SELECTED if index == self.selected else CARD,
                                 edge=AMBER if index == self.selected else EDGE)
                self._item_icon(screen, item, card.left + 13, card.top + 17)
                bottom = self._paragraph(screen, item.get("name", "Unnamed item"), card.left + 49, card.top + 12, card.width - 58, PARCHMENT, font=self.bold_font)
                self._paragraph(screen, self._item_markers(item), card.left + 49, bottom + 5, card.width - 58, TEAL if item.get("equipped") else MUTED, font=self.small_font)
                self.hit_targets.append((card.clip(pack_rect), "item", index))
            y += height + 8
        if not items:
            self._paragraph(screen, "Your pack is empty." if self.tab == "all" else "Nothing in this category yet.", pack_rect.left + 12, pack_rect.top + 18, pack_rect.width - 30)
        screen.set_clip(self.detail_rect)
        draw_pixel_frame(pg, screen, self.detail_rect, fill=CARD)
        selected = self._selected_item()
        if selected:
            self.detail_body_rect = self.detail_rect.copy()
            self.detail_body_rect.height = max(1, self.detail_rect.height - self._item_dock_height(selected) - 3)
            screen.set_clip(self.detail_body_rect)
            previous_scroll = self.detail_scroll
            detail_height = self._draw_item_detail(screen, selected)
            self.max_detail_scroll = max(0, detail_height - self.detail_body_rect.height)
            self.detail_scroll = min(self.detail_scroll, self.max_detail_scroll)
            if self.detail_scroll != previous_scroll:
                screen.fill(CARD, self.detail_body_rect)
                self._draw_item_detail(screen, selected)
            screen.set_clip(self.detail_rect)
            self._draw_item_action_dock(screen, selected)
        else:
            self.max_detail_scroll = self.detail_scroll = 0
            self._paragraph(screen, "Every object on the road has a story. Select an item to inspect it.", self.detail_rect.left + 18, self.detail_rect.top + 24, self.detail_rect.width - 36)
        pg.draw.rect(screen, EDGE, self.detail_rect, 1)
        screen.set_clip(region)
        self._scrollbar(screen, pack_rect, self.scroll, self.max_scroll)
        self._scrollbar(screen, self.detail_body_rect, self.detail_scroll, self.max_detail_scroll, key="detail")

    @staticmethod
    def _item_markers(item: dict[str, Any]) -> str:
        markers = [f"x{_number(item.get('count', 1))}", str(item.get("kind", "item")).capitalize()]
        if item.get("equipped"):
            markers.append("EQUIPPED")
        return "  /  ".join(markers)

    def _item_action_details(self, item: dict[str, Any]) -> tuple[str, str, Any, Any]:
        action = self._item_action()
        label, summary, color = "Keepsake", "Kept for the journey", MUTED
        if item.get("slot"):
            difference, statistic = self._equipment_difference(item)
            if item.get("equipped"):
                key = "attack" if item.get("slot") == "weapon" else "defense"
                label, summary, color = "Equipped", f"Provides +{_number(item.get(key))} {statistic}", TEAL
            else:
                label = "Equip  [Enter]"
                summary = f"{difference:+d} {statistic} vs equipped gear" if difference else f"Same {statistic} as equipped gear"
                color = TEAL if difference > 0 else RED if difference < 0 else MUTED
        elif _number(item.get("healing")) > 0:
            recovered = self._recovery_amount(item)
            label = "Use  [Enter]" if action else "Health is full"
            summary = f"Recover {recovered} Health / x{_number(item.get('count', 1))} in pack" if recovered else "No healing needed; keep this supply"
            color = TEAL if recovered else MUTED
        elif item.get("kind") == "consumable":
            label, summary = "Story item", "Use when a story choice offers it"
        return label, summary, color, action

    def _item_dock_height(self, item: dict[str, Any]) -> int:
        _, summary, _, _ = self._item_action_details(item)
        summary_height = len(_wrap(summary, self.small_font, max(1, self.detail_rect.width - 36))) * (self.small_font.get_linesize() + 1)
        return max(77, summary_height + max(32, self.bold_font.get_linesize() + 8) + 23)

    def _draw_item_action_dock(self, screen: Any, item: dict[str, Any]) -> None:
        rect = self.detail_rect
        x, width = rect.left + 18, rect.width - 36
        height = self._item_dock_height(item)
        top = rect.bottom - height
        self.pg.draw.rect(screen, CARD, (rect.left, top, rect.width, height))
        self.pg.draw.line(screen, EDGE, (x, top), (x + width, top))
        label, summary, color, action = self._item_action_details(item)
        lines = _wrap(summary, self.small_font, width)
        summary_y = top + 7
        for line in lines:
            self._text(screen, line, x, summary_y, color, font=self.small_font)
            summary_y += self.small_font.get_linesize() + 1
        button_height = max(32, self.bold_font.get_linesize() + 8)
        self._button(screen, self.pg.Rect(x, rect.bottom - button_height - 7, width, button_height), label, "item_action", primary=bool(action), enabled=bool(action))

    def _draw_item_detail(self, screen: Any, item: dict[str, Any]) -> int:
        pg = self.pg
        rect = self.detail_rect
        start_y = rect.top - self.detail_scroll
        x, width = rect.left + 20, rect.width - 40
        compact = self.detail_body_rect.height < 180
        y = start_y + (14 if compact else 24)
        self._item_icon(screen, item, x, y, 2 if compact else 3)
        if compact:
            y = self._paragraph(screen, item.get("name", "Unnamed item"), x + 36, y, width - 36, PARCHMENT, font=self.bold_font) + 4
        else:
            y = self._paragraph(screen, item.get("name", "Unnamed item"), x, y + 49, width, PARCHMENT, font=self.title_font) + 8
        label = "Currently equipped" if item.get("equipped") else str(item.get("kind", "item")).capitalize()
        self._text(screen, label, x, y, TEAL if item.get("equipped") else AMBER, font=self.small_font)
        y += self.small_font.get_linesize() + (9 if compact else 17)
        y = self._paragraph(screen, item.get("description", ""), x, y, width) + 23
        for key, label, color in (("attack", "Attack", AMBER), ("defense", "Armor", TEAL), ("healing", "Healing capacity", TEAL)):
            amount = _number(item.get(key))
            if key == "healing":
                amount = _number(item.get("healing_effective", amount))
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
        # Show the authored face at an integer scale, keeping the smaller
        # identity block when reading space is scarce.
        compact = self.content_rect.height < 330
        portrait_scale = 2 if self.content_rect.height >= 640 and width >= 760 else 1
        portrait_padding = 4 if compact else 12
        portrait_width, portrait_height = 64 * portrait_scale + portrait_padding, 80 * portrait_scale + portrait_padding
        header_x = x + portrait_width + 22 if width >= 500 else x
        if width >= 500:
            portrait_rect = self.pg.Rect(x, y, portrait_width, portrait_height)
            draw_pixel_frame(self.pg, screen, portrait_rect, fill=CARD, edge=TEAL)
            self._identity_portrait(screen, character.get("origin"), portrait_rect.inflate(-portrait_padding, -portrait_padding))
        header_width = width - (header_x - x)
        header_top = y
        y = self._paragraph(screen, character.get("name", "Traveler"), header_x, y + 4, header_width, PARCHMENT, font=self.title_font) + 5
        origin = character.get("origin_label", character.get("origin_name", character.get("origin", "A traveler of the old roads")))
        origin_label = str(origin).replace("_", " ").title() if "_" in str(origin) else str(origin)
        y = self._paragraph(screen, origin_label, header_x, y, header_width, TEAL) + (5 if compact else 13)
        y = max(y + (5 if compact else 18), header_top + portrait_height + (2 if compact else 25) if width >= 500 else y + 18)
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
            draw_pixel_frame(self.pg, screen, box, fill=CARD, edge=EDGE)
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
            if character.get("ability_rules"):
                y = self._paragraph(screen, character["ability_rules"], x, y, width, AMBER, font=self.small_font) + 5
            y = self._paragraph(screen, character.get("ability_description", self.data.get("ability_description", "")), x, y, width) + 15
            y = self._paragraph(screen, "Focus refills when a battle begins. Defend restores 1 Focus during battle.", x, y, width, MUTED, font=self.small_font) + 15
        if character.get("origin_description"):
            y = self._section(screen, "Background", x, y + 12, width)
            y = self._paragraph(screen, character["origin_description"], x, y, width) + 15
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
            icon_item = item if isinstance(item, dict) else next((
                other for other in self.data.get("items", [])
                if isinstance(other, dict) and other.get("slot") == slot and other.get("equipped")
            ), None)
            if icon_item is not None:
                self._item_icon(screen, icon_item, x + 3, y + 3)
            else:
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
            status = str(companion.get("status") or "").strip() or ("Traveling with you" if present else "Not traveling with you")
            trust_label = "Trusted" if trust >= 2 else "Steady" if trust >= 0 else "Wary"
            status_line = f"{status}  /  {trust_label} ({trust:+d})" if "trust" in companion else status
            top = y
            portrait_row = {"mara": 4, "tobin": 5, "calenor": 6}.get(str(companion.get("name", "")).casefold())
            text_x = x + (69 if portrait_row is not None else 14)
            text_width = width - (text_x - x) - 14
            name_height = len(_wrap(companion.get("name", "Companion"), self.bold_font, text_width)) * self.line_height
            status_height = len(_wrap(status_line, self.small_font, text_width)) * (self.small_font.get_linesize() + 3)
            height = max(88, name_height + status_height + 32)
            draw_pixel_frame(self.pg, screen, (x, y, width, height), fill=CARD)
            if portrait_row is not None:
                self._companion_portrait(screen, companion.get("name"), x + 12, y + 15)
            y = self._paragraph(screen, companion.get("name", "Companion"), text_x, y + 12, text_width, PARCHMENT, font=self.bold_font) + 5
            y = self._paragraph(screen, status_line, text_x, y, text_width, TEAL if present and trust >= 0 else MUTED, font=self.small_font)
            y = max(y + 12, top + height + 10)
        if any(isinstance(companion, dict) and "trust" in companion for companion in companions):
            y = self._paragraph(screen, "Trust can change conversations and the aid companions offer in battle.", x, y + 8, width, MUTED, font=self.small_font) + 15
        return y + 8

    def _journal_entries(self) -> list[Any]:
        aliases = {
            "active": ("activequests", "active_quests", "quests"),
            "completed": ("completedquests", "completed_quests"),
            "clues": ("clues", "journal"),
        }
        for key in aliases.get(self.tab, ()):
            if key in self.data:
                return self.data[key] or []
        return []

    def _draw_journal(self, screen: Any, x: int, y: int, width: int) -> int:
        start_y = y
        if self.tab == "decision":
            return self._draw_decision(screen, x, y, width)
        entries = self._journal_entries()
        if not entries:
            messages = {"active": "No unfinished promises. New quests will appear as the road unfolds.", "completed": "Your completed quests will be remembered here.", "clues": "No clues recorded yet. Listen closely, and keep your eyes on the road."}
            return self._paragraph(screen, messages[self.tab], x + 18, y + 20, width - 36) - start_y + 25
        details = {entry.get("title"): entry for entry in self.data.get("quest_details", []) if isinstance(entry, dict)}
        if self.tab == "clues":
            self._text(screen, f"NEWEST NOTES FIRST  /  {len(entries)} recorded", x, y, TEAL, font=self.small_font)
            y += 33
            entries = list(reversed(entries))
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                title = entry.get("title", entry.get("name", "A note from the road"))
                description = entry.get("description", entry.get("text", ""))
            else:
                title, description = str(entry), ""
            detail = details.get(title, {}) if self.tab == "active" else {}
            guidance = str(detail.get("guidance", ""))
            progress = str(detail.get("progress", ""))
            related = detail.get("related_clues", [])
            lead = str(related[0]) if related else ""
            title_lines = _wrap(title, self.bold_font, width - 66)
            body_lines = _wrap(description, self.font, width - 66) if description else []
            height = 30 + len(title_lines) * self.line_height + len(body_lines) * self.line_height + (12 if body_lines else 8)
            if progress:
                height += len(_wrap(progress, self.bold_font, width - 66)) * self.line_height + 10
            if guidance:
                height += len(_wrap(guidance, self.font, width - 66)) * self.line_height + 10
            if lead:
                height += len(_wrap(f"Recorded lead: {lead}", self.small_font, width - 66)) * (self.small_font.get_linesize() + 3) + 10
            card = self.pg.Rect(x, y, width, height)
            self.pg.draw.rect(screen, CARD, card)
            self.pg.draw.rect(screen, EDGE, card, 1)
            self.pg.draw.rect(screen, TEAL if self.tab == "completed" else AMBER, (x, y, 3, height))
            self._text(screen, f"{index + 1:02d}", x + 13, y + 15, TEAL if self.tab == "completed" else AMBER, font=self.small_font)
            text_y = self._paragraph(screen, title, x + 48, y + 13, width - 66, PARCHMENT, font=self.bold_font)
            if description:
                text_y = self._paragraph(screen, description, x + 48, text_y + 8, width - 66)
            if progress:
                text_y = self._paragraph(screen, progress, x + 48, text_y + 8, width - 66, TEAL, font=self.bold_font)
            if guidance:
                text_y = self._paragraph(screen, guidance, x + 48, text_y + 8, width - 66)
            if lead:
                self._paragraph(screen, f"Recorded lead: {lead}", x + 48, text_y + 8, width - 66, TEAL, font=self.small_font)
            y += height + 13
        return y - start_y

    def _draw_decision(self, screen: Any, x: int, y: int, width: int) -> int:
        """Show exact current options without submitting an engine choice."""
        start_y = y
        location = self.data.get("location", "Your present stop")
        y = self._paragraph(screen, location, x, y, width, PARCHMENT, font=self.title_font) + 5
        chapter = self.data.get("chapter")
        if chapter:
            self._text(screen, f"PART { {1: 'I', 2: 'II'}.get(_number(chapter), chapter) }  /  YOU ARE HERE", x, y, AMBER, font=self.small_font)
            y += 32
        decision = self.data.get("decision") or {}
        options = decision.get("options", []) if isinstance(decision, dict) else []
        if not options:
            message = "Places you have already explored are recorded under Remembered roads." if self.kind == "map" else "Your journal records the promises and clues you have collected. Return to the scene to continue."
            y = self._paragraph(screen, message, x, y + 14, width) + 20
            return y - start_y
        y = self._section(screen, "Choices at this stop", x, y + 8, width)
        heading = decision.get("heading", "")
        if heading:
            y = self._paragraph(screen, heading, x, y, width, TEAL, font=self.small_font) + 12
        for index, option in enumerate(options, 1):
            lines = _wrap(option, self.font, width - 61)
            height = max(54, 25 + len(lines) * self.line_height)
            self.pg.draw.rect(screen, CARD, (x, y, width, height))
            self.pg.draw.rect(screen, EDGE, (x, y, width, height), 1)
            self._text(screen, f"{index:02d}", x + 13, y + 14, AMBER, font=self.small_font)
            self._paragraph(screen, option, x + 43, y + 11, width - 61, PARCHMENT)
            y += height + 9
        y = self._paragraph(screen, "Return to the scene to make a choice.", x, y + 12, width, MUTED, font=self.small_font) + 12
        return y - start_y

    def _draw_map(self, screen: Any, x: int, y: int, width: int) -> int:
        if self.tab == "here":
            return self._draw_decision(screen, x, y, width)
        start_y = y
        route = self.data.get("route", self.data.get("locations", []))
        if not route:
            route = [{"name": name, "visited": True} for name in self.data.get("visited", [])]
        if not route:
            return self._paragraph(screen, "The first step is still ahead. Places you have visited will appear here.", x + 18, y + 20, width - 36) - start_y + 25
        remembered = sum(bool(location.get("visited")) if isinstance(location, dict) else True for location in route)
        self._text(screen, f"{remembered} PLACES REMEMBERED", x, y, TEAL, font=self.small_font)
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
        notice = str(self.data.get("notice") or "").strip()
        if notice:
            y = self._paragraph(screen, notice, x, y, width, AMBER, font=self.small_font) + 18
        if self.tab == "all":
            completed = max(0, _number(self.data.get("completed_runs")))
            y = self._paragraph(screen, f"Completed episodes: {completed}", x, y, width, TEAL, font=self.bold_font) + 8
            if "part_one_completions" in self.data and "part_two_completions" in self.data:
                y = self._paragraph(screen, f"Part I: {_number(self.data['part_one_completions'])}  /  Part II: {_number(self.data['part_two_completions'])}", x, y, width, MUTED, font=self.small_font) + 18
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
        heading = f"Earned deeds: {earned}" if self.tab == "earned" else f"Still to discover: {len(achievements) - earned}" if self.tab == "open" else f"Achievements  /  {earned} of {len(achievements)} earned"
        y = self._paragraph(screen, heading, x, y + (14 if self.tab == "all" else 0), width, AMBER, font=self.bold_font) + 14
        if self.tab == "earned":
            achievements = [entry for entry in achievements if entry.get("earned")]
        elif self.tab == "open":
            achievements = [entry for entry in achievements if not entry.get("earned")]
        if not achievements:
            empty = "No deeds earned yet. Completed episodes and their achievements will be remembered here." if self.tab == "earned" else "Every deed in this chronicle has been earned." if self.tab == "open" else "Your deeds will be remembered here."
            y = self._paragraph(screen, empty, x, y, width) + 16
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

    def _slot_lines(self, slot: dict[str, Any], mode: str) -> list[tuple[str, Any, Any]]:
        if slot.get("corrupt"):
            return [("Cannot be loaded." if mode == "load" else "Replace this damaged memory.", MUTED, self.small_font)]
        if slot.get("empty"):
            return [("A place for your journey" if mode == "save" else "No journey saved here", MUTED, self.small_font)]
        chapter = slot.get("chapter", "?")
        part = {1: "I", 2: "II"}.get(_number(chapter), chapter)
        place = str(slot.get("location", ""))
        episode = f"Part {part}{' complete' if slot.get('ending') else ''}"
        lines = [(f"{episode} / {place}" if place else episode, TEAL, self.font)]
        if "hp" in slot and "max_hp" in slot:
            lines.append((f"Health {_number(slot['hp'])}/{_number(slot.get('max_hp'))}", MUTED, self.small_font))
        saved_at = slot.get("saved_at")
        if isinstance(saved_at, str) and saved_at != "unknown":
            try:
                moment = datetime.fromisoformat(saved_at.replace("Z", "+00:00")).astimezone()
                stamp = moment.strftime("%b %d, %Y %H:%M %Z")
                lines.append((f"Saved {stamp}", MUTED, self.small_font))
            except (ValueError, OverflowError, OSError):
                pass
        return lines

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
            height = 48 + len(_wrap(title, self.bold_font, text_width)) * self.line_height
            for text, _, font in self._slot_lines(slot, mode):
                height += len(_wrap(text, font, text_width)) * (font.get_linesize() + 3) + 6
            card_heights.append(max(109, height) + (42 if width < 500 else 0))
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
            draw_pixel_frame(self.pg, screen, card, fill=SELECTED if index == self.selected else CARD,
                             edge=RED if corrupt else AMBER if index == self.selected else EDGE)
            label = f"CAMP {slot.get('slot', slot.get('id', index + 1))}"
            self._text(screen, label, x + 16, y + 11, AMBER, font=self.small_font)
            bottom = self._paragraph(screen, title, x + 16, y + 33, text_width, RED if corrupt else MUTED if empty else PARCHMENT, font=self.bold_font)
            for text, color, font in self._slot_lines(slot, mode):
                bottom = self._paragraph(screen, text, x + 16, bottom + 6, text_width, color, font=font)
            button_label = "Load memory" if mode == "load" else "Save here" if empty else "Overwrite..."
            button = self.pg.Rect(x + width - 164, y + (height - 37) // 2, 148, 37) if width >= 500 else self.pg.Rect(x + 16, y + height - 47, min(180, width - 32), 35)
            visible = card.clip(self.content_rect)
            if visible.width and visible.height:
                self.hit_targets.append((visible, "slot", index))
            enabled = not (mode == "load" and (empty or corrupt))
            self._button(screen, button, button_label if enabled else "Unavailable", "slot_action", index, primary=index == self.selected, enabled=enabled)
            y += height + 12
        return y - start_y
