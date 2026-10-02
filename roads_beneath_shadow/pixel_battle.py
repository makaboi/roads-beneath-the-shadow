"""An animated battlefield for the engine's immutable combat snapshots.

Pygame is passed in by the window. Importing this module neither imports pygame
nor starts SDL, and drawing never changes the combat state.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from .combat_view import CombatFeedback, CombatSnapshot


INK = (16, 21, 27)
PANEL = (24, 31, 36)
EDGE = (61, 68, 64)
BONE = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 172, 159)
MUTED = (164, 167, 153)
RED = (229, 136, 111)
SHADOW = (9, 13, 17)
ASSET_DIR = Path(__file__).resolve().parent / "pixel_assets"


@dataclass
class _Effect:
    feedback: CombatFeedback
    age: float = 0.0
    duration: float = 1.05


class _ScaledFont:
    """Keep measured text and rendered glyphs identical when fitting a card.

    System font names resolve differently on macOS, Linux, and Windows. A
    requested point size alone cannot guarantee the same line height or width.
    """

    def __init__(self, pg: Any, font: Any, scale: float) -> None:
        self.pg = pg
        self.font = font
        self.scale = scale

    def size(self, text: str) -> tuple[int, int]:
        width, height = self.font.size(text)
        return math.ceil(width * self.scale), math.ceil(height * self.scale)

    def get_linesize(self) -> int:
        return max(1, math.ceil(self.font.get_linesize() * self.scale))

    def render(self, *args: Any, **kwargs: Any) -> Any:
        glyph = self.font.render(*args, **kwargs)
        return self.pg.transform.scale(glyph, (max(1, math.ceil(glyph.get_width() * self.scale)), max(1, math.ceil(glyph.get_height() * self.scale))))


def _wrapped(text: str, font: Any, width: int) -> list[str]:
    """Measure whole words, splitting a long identifier only when necessary."""
    width = max(1, width)
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
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


class BattleView:
    """A standalone main-thread renderer with selectable enemy cards.

    ``update`` receives seconds. ``handle_event`` returns ``(handled, target_id)``;
    the window decides whether that target is valid for its current request.
    Enemy IDs come directly from snapshots, including after a foe falls.
    """

    def __init__(self, pg: Any) -> None:
        self.pg = pg
        self.snapshot: CombatSnapshot | None = None
        self.font = pg.font.SysFont("dejavusansmono,courier,monospace", 13)
        self.bold_font = pg.font.SysFont("dejavusansmono,courier,monospace", 13, bold=True)
        self.compact_bold_font = pg.font.SysFont("dejavusansmono,courier,monospace", 12, bold=True)
        self.mini_bold_font = pg.font.SysFont("dejavusansmono,courier,monospace", 10, bold=True)
        self.mini_font = pg.font.SysFont("dejavusansmono,courier,monospace", 10)
        self.mini_prose_font = pg.font.SysFont("dejavusans,arial,sans", 10)
        self.small_font = pg.font.SysFont("dejavusansmono,courier,monospace", 11)
        self.banner_font = pg.font.SysFont("dejavusansmono,courier,monospace", 16, bold=True)
        self.number_font = pg.font.SysFont("dejavusansmono,courier,monospace", 19, bold=True)
        self.enemy_hits: list[tuple[Any, str]] = []
        self.sprite_hits: list[tuple[Any, str]] = []
        self.actor_positions: dict[str, tuple[int, int]] = {}
        self.hovered_id: str | None = None
        self.tooltip_hits: list[tuple[Any, str]] = []
        self._mouse: tuple[int, int] | None = None
        self._effects: list[_Effect] = []
        self._sprites: dict[tuple[str, bool, int], Any] = {}
        self._fitted_fonts: dict[tuple[int, float], Any] = {}
        self._typography_cache: dict[tuple[Any, ...], tuple[bool, Any, Any, Any]] = {}
        self._character_atlas: Any = None
        self._atlas_checked = False
        self._backdrops: dict[str, Any] = {}
        self._scaled_backdrop: tuple[Any, tuple[int, int], Any] | None = None
        self._scene_override: str | Any | None = None
        self._rect = pg.Rect(0, 0, 0, 0)
        self._arena_rect = pg.Rect(0, 0, 0, 0)
        self._reduced_motion = False
        self._time = 0.0

    def set_snapshot(self, snapshot: CombatSnapshot | None) -> None:
        """Replace presentation data without retaining mutable engine objects."""
        self._typography_cache.clear()
        if snapshot is None:
            self._effects.clear()
            self.enemy_hits.clear()
            self.sprite_hits.clear()
            self.actor_positions.clear()
            self.hovered_id = None
        self.snapshot = snapshot

    def set_scene(self, scene: str | Any | None) -> None:
        """Use a packaged scene key or the window's already loaded illustration."""
        if scene is self._scene_override or isinstance(scene, str) and scene == self._scene_override:
            return
        self._scene_override = scene
        self._scaled_backdrop = None

    def queue_feedback(self, feedback: CombatFeedback) -> None:
        if feedback.kind in {"inspect", "notice", "info"}:
            return
        # A whole resolved turn arrives in one queue drain. Stagger its visual
        # hits so each attacker and damage amount can be read independently.
        delay = min(1.0, len(self._effects) * 0.19)
        self._effects.append(_Effect(feedback, age=-delay))

    def update(self, dt: float, reduced_motion: bool = False) -> None:
        self._reduced_motion = bool(reduced_motion)
        dt = max(0.0, float(dt))
        self._time += dt
        for effect in self._effects:
            effect.age += dt
        self._effects[:] = [effect for effect in self._effects if effect.age < effect.duration]

    def handle_event(self, event: Any) -> tuple[bool, str | None]:
        if self.snapshot is None:
            return False, None
        if event.type == self.pg.MOUSEMOTION:
            self._mouse = tuple(event.pos)
            self.hovered_id = next(
                (enemy_id for rect, enemy_id in self.enemy_hits + self.sprite_hits if rect.collidepoint(event.pos)), None
            )
            return False, None
        if event.type != self.pg.MOUSEBUTTONDOWN or event.button != 1:
            return False, None
        for rect, enemy_id in self.enemy_hits + self.sprite_hits:
            if rect.collidepoint(event.pos):
                enemy = next((enemy for enemy in self.snapshot.enemies if enemy.id == enemy_id), None)
                if enemy is not None and enemy.hp > 0 and self.snapshot.phase == "active":
                    return True, enemy_id
                return True, None
        return False, None

    def _text(self, surface: Any, text: str, pos: tuple[int, int], color: tuple[int, int, int] = BONE, *, font: Any = None) -> None:
        surface.blit((font or self.font).render(str(text), True, color), pos)

    def _paragraph(self, surface: Any, text: str, pos: tuple[int, int], width: int, color: tuple[int, int, int] = BONE, *, font: Any = None) -> int:
        font = font or self.font
        x, y = pos
        for line in _wrapped(text, font, width):
            self._text(surface, line, (x, y), color, font=font)
            y += font.get_linesize()
        return y

    def _backdrop(self) -> Any:
        scene = self._scene_override
        if scene is not None and not isinstance(scene, str):
            return scene
        if not scene:
            enemies = self.snapshot.enemies if self.snapshot else ()
            names = " ".join(enemy.archetype + " " + enemy.name for enemy in enemies).casefold()
            scene = "seal" if any(word in names for word in ("warden", "troll", "seal")) else "marsh"
            if any(word in names for word in ("ranger", "teren")):
                scene = "tavern-interior"
        if scene not in self._backdrops:
            try:
                self._backdrops[scene] = self.pg.image.load(str(ASSET_DIR / f"{scene}.png"))
            except (OSError, self.pg.error):
                self._backdrops[scene] = None
        return self._backdrops[scene]

    def _draw_backdrop(self, surface: Any, rect: Any) -> None:
        pg = self.pg
        image = self._backdrop()
        pg.draw.rect(surface, SHADOW, rect)
        if image is not None and rect.w > 0 and rect.h > 0:
            cache = self._scaled_backdrop
            if cache is None or cache[0] is not image or cache[1] != rect.size:
                scale = max(rect.w / image.get_width(), rect.h / image.get_height())
                scaled = pg.transform.scale(image, (math.ceil(image.get_width() * scale), math.ceil(image.get_height() * scale)))
                self._scaled_backdrop = (image, rect.size, scaled)
            scaled = self._scaled_backdrop[2]
            surface.blit(scaled, rect, pg.Rect((scaled.get_width() - rect.w) // 2, max(0, (scaled.get_height() - rect.h) // 3), rect.w, rect.h))
        veil = pg.Surface(rect.size, pg.SRCALPHA)
        veil.fill((*INK, 88))
        for y in range(0, rect.h, 4):
            # Mist catches the distant architecture; the foreground becomes
            # a quiet dark stage rather than hiding sprites in the illustration.
            alpha = min(218, 35 + int(185 * (y / max(1, rect.h)) ** 1.7))
            pg.draw.rect(veil, (*INK, alpha), (0, y, rect.w, 4))
        surface.blit(veil, rect)
        pg.draw.line(surface, EDGE, (rect.x, rect.bottom - 1), (rect.right, rect.bottom - 1))

    @staticmethod
    def _kind(name: str) -> str:
        name = name.casefold()
        if "warg" in name or "wolf" in name:
            return "warg"
        if "troll" in name:
            return "troll"
        if "ghorak" in name:
            return "ghorak"
        if "rider" in name or "shadow" in name:
            return "rider"
        if "mara" in name:
            return "mara"
        if "tobin" in name:
            return "tobin"
        if "player" in name or "traveler" in name:
            return "player"
        if "ranger" in name or "teren" in name:
            return "ranger"
        if "archer" in name:
            return "archer"
        if "sapper" in name or "saboteur" in name:
            return "sapper"
        if "captain" in name or "commander" in name:
            return "captain"
        return "orc"

    def _sprite(self, kind: str, facing_left: bool, pose: int = 0) -> Any:
        key = (kind, facing_left, pose)
        if key in self._sprites:
            return self._sprites[key]
        pg = self.pg
        sprite = pg.Surface((40, 48), pg.SRCALPHA)

        if not self._atlas_checked:
            self._atlas_checked = True
            try:
                self._character_atlas = pg.image.load(str(ASSET_DIR / "world-characters.png"))
            except (OSError, pg.error):
                pass
        # The traveler and companions share their exact coats and silhouettes
        # with the exploration maps. Original encounter creatures follow the
        # same palette while keeping different weapons and body shapes.
        atlas_rows = {"player": 2, "mara": 4, "tobin": 5}
        if self._character_atlas is not None and kind in atlas_rows:
            row = atlas_rows[kind]
            native = self._character_atlas.subsurface(pg.Rect((2 if pose else 0) * 20, row * 24, 20, 24))
            sprite = pg.transform.scale(native, (40, 48))
            if kind == "tobin":
                pg.draw.lines(sprite, AMBER, False, [(29, 15), (33, 21), (34, 27), (32, 34), (28, 37)], 1)
                pg.draw.line(sprite, MUTED, (29, 15), (28, 37))
            else:
                pg.draw.line(sprite, BONE, (28, 29), (35, 17 if pose else 21), 1)
                pg.draw.line(sprite, AMBER, (26, 30), (31, 30), 1)
                if kind == "mara":
                    pg.draw.line(sprite, BONE, (11, 29), (5, 21), 1)
            if facing_left:
                sprite = pg.transform.flip(sprite, True, False)
            self._sprites[key] = sprite
            return sprite

        def box(color: tuple[int, int, int], bounds: tuple[int, int, int, int]) -> None:
            pg.draw.rect(sprite, color, bounds)

        if kind == "warg":
            fur, lit = (68, 63, 59), (125, 115, 92)
            pg.draw.polygon(sprite, SHADOW, [(2, 31), (10, 26), (17, 24), (27, 25), (31, 20), (34, 23), (37, 30), (40, 34), (34, 38), (32, 45), (28, 45), (27, 37), (16, 37), (13, 45), (9, 45), (10, 36), (4, 36)])
            pg.draw.polygon(sprite, fur, [(4, 31), (12, 28), (24, 27), (31, 28), (34, 24), (35, 31), (38, 33), (34, 36), (28, 35), (15, 35), (8, 34)])
            box(lit, (13, 28, 12, 2))
            box((95, 88, 73), (22, 29, 9, 4))
            box(AMBER, (34, 31, 2, 1))
            box(BONE, (35, 35, 2, 2))
            box(fur, (11, 36, 2, 7))
            box(fur, (29, 36, 2, 7))
            box((30, 29, 30), (17, 31, 3, 2))
        else:
            giant = kind in ("troll", "ghorak", "captain")
            cloak = {"player": (45, 78, 75), "mara": (109, 56, 47), "tobin": (88, 82, 48), "ranger": (56, 75, 62), "orc": (79, 73, 52), "archer": (75, 83, 62), "sapper": (117, 82, 46), "captain": (98, 77, 53), "ghorak": (107, 61, 47), "troll": (84, 83, 69), "rider": (32, 33, 41)}[kind]
            light = tuple(min(255, channel + 27) for channel in cloak)
            skin = (129, 127, 90) if kind in ("orc", "archer", "sapper", "captain", "troll", "ghorak") else (193, 160, 119)
            shoulder = 6 if giant else 10
            head_y = 3 if giant else 7
            # The silhouette has a hood, shoulder plates, broken cloak hem,
            # individual boots and an exposed sword hand, all on a pixel grid.
            pg.draw.polygon(sprite, SHADOW, [(14, head_y), (25, head_y), (28, head_y + 10), (34 - shoulder // 2, 20), (35 if giant else 30, 37), (27, 40), (26, 46), (20, 46), (19, 40), (16, 40), (15, 46), (9, 46), (10, 39), (4 if giant else 7, 37), (shoulder, 21), (11, 18)])
            pg.draw.polygon(sprite, cloak, [(14, head_y + 2), (24, head_y + 2), (26, head_y + 11), (29 if giant else 26, 21), (31 if giant else 27, 36), (24, 38), (21, 35), (17, 39), (9 if giant else 10, 35), (shoulder + 2, 22), (13, 18)])
            box(light, (13, 21, 3, 12))
            box(light, (16, head_y + 2, 7, 2))
            box(skin, (17, head_y + 6, 7, 7))
            box(SHADOW, (17, head_y + 6, 7, 2))
            box(SHADOW, (18, head_y + 9, 1, 1))
            box(AMBER if kind in ("orc", "archer", "sapper", "captain", "ghorak", "rider") else SHADOW, (22, head_y + 9, 1, 1))
            box((59, 46, 34), (11, 38, 4, 6))
            box((59, 46, 34), (21, 38, 4, 6))
            box((113, 94, 65), (11, 27, 16 if giant else 14, 2))
            box(AMBER, (19, 27, 2, 2))
            box(skin, (26 if giant else 25, 25, 3, 5))
            if kind in ("tobin", "archer"):
                pg.draw.lines(sprite, AMBER, False, [(30, 16), (34, 21), (35, 27), (33, 33), (29, 37)], 1)
                pg.draw.line(sprite, MUTED, (30, 16), (29, 37))
                box(BONE, (27, 26, 10, 1))
            elif kind in ("troll", "sapper"):
                box((117, 95, 65), (29, 17, 3, 25))
                box((139, 127, 105), (26, 14, 9, 8))
                box((72, 65, 54), (27, 15, 6, 2))
            elif kind == "rider":
                box((156, 149, 133), (28, 13, 2, 24))
                box((204, 196, 158), (29, 13, 1, 21))
            else:
                blade_y = 14 if pose else 20
                pg.draw.line(sprite, (77, 82, 79), (28, 30), (35, blade_y), 3)
                pg.draw.line(sprite, BONE, (28, 29), (35, blade_y), 1)
                box(AMBER, (26, 29, 6, 2))
                if kind == "mara":
                    pg.draw.line(sprite, BONE, (10, 28), (5, 21), 1)
            if kind in ("orc", "archer", "sapper", "captain", "ghorak"):
                box((99, 105, 97), (9 if giant else 11, 20, 6, 3))
                box((146, 146, 121), (10 if giant else 12, 20, 4, 1))
                box(BONE, (22, head_y + 12, 2, 2))
            if kind == "player":
                # The story's silver star stays visible on the traveler's cloak.
                box(BONE, (18, 23, 5, 1))
                box(BONE, (20, 21, 1, 5))
        if facing_left:
            sprite = pg.transform.flip(sprite, True, False)
        self._sprites[key] = sprite
        return sprite

    def _active_effects(self, actor_id: str) -> list[_Effect]:
        return [effect for effect in self._effects if 0 <= effect.age < effect.duration and effect.feedback.target_id == actor_id]

    def _draw_actor(self, surface: Any, actor_id: str, kind: str, anchor: tuple[int, int], scale: float, *, facing_left: bool, alive: bool = True, targeted: bool = False, now_ms: int = 0) -> None:
        pg = self.pg
        x, ground = anchor
        self.actor_positions[actor_id] = anchor
        effects = self._active_effects(actor_id)
        outgoing = next((effect for effect in self._effects if 0 <= effect.age < 0.32 and effect.feedback.actor_id == actor_id and effect.feedback.kind == "damage" and effect.feedback.target_id != actor_id), None)
        offset = 0
        bob = 0
        if not self._reduced_motion and alive:
            bob = int(math.sin(now_ms / 390 + x / 45) > 0)
            if outgoing:
                offset = round(math.sin(outgoing.age / 0.32 * math.pi) * 12) * (-1 if facing_left else 1)
            if effects and effects[-1].feedback.kind == "damage" and effects[-1].age < 0.24:
                offset += (2 if int(effects[-1].age * 40) % 2 else -2) * scale
        shadow_width = int((35 if kind == "warg" else 27) * scale)
        pg.draw.ellipse(surface, SHADOW, (x - shadow_width // 2, ground - 6, shadow_width, 10))
        if targeted and alive:
            pg.draw.ellipse(surface, AMBER, (x - shadow_width // 2 - 5, ground - 8, shadow_width + 10, 13), 2)
        sprite = self._sprite(kind, facing_left, int(outgoing is not None))
        if not alive:
            sprite = pg.transform.rotate(sprite, 90 if facing_left else -90)
            sprite = sprite.copy()
            sprite.set_alpha(90)
        sprite = pg.transform.scale(sprite, (int(sprite.get_width() * scale), int(sprite.get_height() * scale)))
        sprite_rect = sprite.get_rect(midbottom=(x + offset, ground - bob))
        surface.blit(sprite, sprite_rect)
        if alive and not self._reduced_motion and any(effect.feedback.kind == "damage" and effect.age < 0.12 for effect in effects):
            flash = pg.Surface(sprite.get_size(), pg.SRCALPHA)
            # An outline flash keeps every cloak/weapon pixel visible.
            pg.draw.rect(flash, (*RED, 90), flash.get_rect(), 2)
            surface.blit(flash, sprite_rect)
        if actor_id.startswith("enemy_"):
            self.sprite_hits.append((sprite_rect.inflate(12, 12), actor_id))
            if targeted and alive:
                pg.draw.polygon(surface, AMBER, [(x - 5, sprite_rect.y - 9), (x + 5, sprite_rect.y - 9), (x, sprite_rect.y - 3)])

    def _health(self, surface: Any, rect: Any, hp: int, maximum: int, *, color: tuple[int, int, int] = RED) -> None:
        pg = self.pg
        pg.draw.rect(surface, (43, 45, 44), rect)
        if maximum > 0 and hp > 0:
            fill = rect.copy()
            fill.w = max(1, round(rect.w * min(1, hp / maximum)))
            pg.draw.rect(surface, color, fill)
            pg.draw.line(surface, tuple(min(255, channel + 20) for channel in color), fill.topleft, (fill.right - 1, fill.y))

    def _status_line(self, surface: Any, statuses: Any, x: int, y: int, width: int, *, font: Any = None) -> int:
        text = "  ".join(f"{status.label} {status.remaining}" for status in statuses)
        if not text:
            return y
        start = y
        y = self._paragraph(surface, text, (x, y), width, TEAL, font=font or self.small_font)
        description = "\n".join(f"{status.label}: {status.description}" for status in statuses)
        self.tooltip_hits.append((self.pg.Rect(x, start, width, y - start), description))
        return y

    def _arena_conditions(self, surface: Any, rect: Any) -> None:
        if self.snapshot is None or not self.snapshot.player.statuses:
            return
        text = "  ".join(f"{status.label} {status.remaining}" for status in self.snapshot.player.statuses)
        width = min(rect.w - 20, max(100, round(rect.w * 0.48)))
        lines = _wrapped(text, self.small_font, width - 12)
        height = len(lines) * self.small_font.get_linesize() + 8
        panel = self.pg.Rect(rect.x + 8, rect.y + 6, min(width, max(self.small_font.size(line)[0] for line in lines) + 12), height)
        self.pg.draw.rect(surface, INK, panel)
        self.pg.draw.rect(surface, EDGE, panel, 1)
        y = panel.y + 4
        for line in lines:
            self._text(surface, line, (panel.x + 6, y), TEAL, font=self.small_font)
            y += self.small_font.get_linesize()
        description = "\n".join(f"{status.label}: {status.description}" for status in self.snapshot.player.statuses)
        self.tooltip_hits.append((panel, description))

    @staticmethod
    def _damage_label(enemy: Any) -> str:
        return f"{enemy.damage_min}–{enemy.damage_max} DAMAGE" if enemy.damage_max or enemy.threat in {"attack", "danger"} else str(enemy.threat).upper()

    @staticmethod
    def _status_text(statuses: Any) -> str:
        return "  ".join(f"{status.label} {status.remaining}" for status in statuses)

    @staticmethod
    def _health_label(enemy: Any) -> str:
        return f"{max(0, enemy.hp)} / {enemy.max_hp} HEALTH"

    @staticmethod
    def _armor_label(enemy: Any) -> str:
        return f"ARMOR {enemy.armor}" + (f"  •  PHASE {enemy.phase}" if enemy.phase > 1 else "")

    def _interrupt_label(self, enemy: Any) -> str:
        if enemy.interruptible:
            return "◆ CAN INTERRUPT"
        return "◇ HOLD YOUR GROUND" if self.snapshot and self.snapshot.defensive_objective else "◇ COMMITTED INTENT"

    def _card_content_height(self, rect: Any, enemy: Any, wide: bool, compact: bool, fonts: tuple[Any, Any, Any]) -> int:
        """Measure every visible field using the same spacing as drawing."""
        title_font, body_font, prose_font = fonts
        pad = 7 if compact else 12
        width = rect.w - pad * 2
        title_width = round(width * 0.44) if wide else width
        details_width = width - title_width - 22 if wide else width
        top = 6 if compact else 10

        def paragraph_height(text: str, font: Any, available: int) -> int:
            return len(_wrapped(text, font, available)) * font.get_linesize() if text else 0

        y = top + paragraph_height(enemy.name, title_font, title_width) + (1 if compact else 4)
        y += paragraph_height(self._health_label(enemy), body_font, title_width) + (1 if compact else 4)
        y += 6 if compact else 11  # Health bar and its lower gap.
        y += paragraph_height(self._armor_label(enemy), body_font, title_width) + (2 if compact else 6)
        left_height = y
        statuses = self._status_text(enemy.statuses)
        if wide:
            left_height += paragraph_height(statuses, body_font, title_width)
            y = top
        if enemy.hp <= 0:
            return max(left_height, y + 3 + title_font.get_linesize()) + top
        y += paragraph_height(enemy.intent_label.upper(), title_font, details_width) + (1 if compact else 3)
        y += paragraph_height(self._damage_label(enemy), body_font, details_width) + (2 if compact else 5)
        y += paragraph_height(enemy.telegraph, prose_font, details_width) + (3 if compact else 6)
        y += paragraph_height(self._interrupt_label(enemy), body_font, details_width) + (2 if compact else 6)
        if not wide:
            y += paragraph_height(statuses, body_font, details_width)
        return max(left_height, y) + top

    def _card_typography(self, rect: Any, enemy: Any, wide: bool) -> tuple[bool, Any, Any, Any]:
        key = (enemy, rect.w, rect.h, wide, bool(self.snapshot and self.snapshot.defensive_objective),
               *(id(font) for font in (self.bold_font, self.compact_bold_font, self.small_font,
                                       self.mini_bold_font, self.mini_font, self.mini_prose_font)))
        if key in self._typography_cache:
            return self._typography_cache[key]

        def remember(style: tuple[bool, Any, Any, Any]) -> tuple[bool, Any, Any, Any]:
            # Resize events can produce many dimensions in one snapshot; keep
            # fitting work off ordinary animation frames without growing an
            # unbounded layout cache during a long drag of the window border.
            if len(self._typography_cache) >= 64:
                self._typography_cache.clear()
            self._typography_cache[key] = style
            return style

        compact = rect.h < 180
        fonts = (self.mini_bold_font if compact else self.compact_bold_font if rect.w < 180 else self.bold_font,
                 self.mini_font if compact else self.small_font,
                 self.mini_prose_font if compact else self.small_font)
        if self._card_content_height(rect, enemy, wide, compact, fonts) <= rect.h:
            return remember((compact, *fonts))
        compact = True
        fonts = (self.mini_bold_font, self.mini_font, self.mini_prose_font)
        if self._card_content_height(rect, enemy, wide, compact, fonts) <= rect.h:
            return remember((compact, *fonts))

        def scaled_fonts(scale: float) -> tuple[Any, Any, Any]:
            output = []
            for font in fonts:
                key = (id(font), scale)
                if key not in self._fitted_fonts:
                    self._fitted_fonts[key] = _ScaledFont(self.pg, font, scale)
                output.append(self._fitted_fonts[key])
            return tuple(output)

        # Find the largest readable scale which preserves every card field.
        # Wrapping is recalculated at each candidate; scaling a height estimate
        # alone would miss extra lines caused by a platform's wider glyphs.
        lower, upper = 0.35, 1.0
        fitted = scaled_fonts(lower)
        for _ in range(9):
            candidate = round((lower + upper) / 2, 4)
            candidate_fonts = scaled_fonts(candidate)
            if self._card_content_height(rect, enemy, wide, compact, candidate_fonts) <= rect.h:
                lower = candidate
                fitted = candidate_fonts
            else:
                upper = candidate
        return remember((compact, *fitted))

    def _draw_card(self, surface: Any, rect: Any, enemy: Any, *, wide: bool = False) -> None:
        pg = self.pg
        alive = enemy.hp > 0
        selected = self.snapshot is not None and enemy.id == self.snapshot.target_id and alive
        hovered = enemy.id == self.hovered_id and alive
        pg.draw.rect(surface, (29, 35, 38) if selected else PANEL, rect)
        pg.draw.rect(surface, AMBER if selected else TEAL if hovered else EDGE, rect, 2 if selected else 1)
        if selected:
            pg.draw.rect(surface, AMBER, (rect.x, rect.y, 4, rect.h))
        self.enemy_hits.append((rect.copy(), enemy.id))
        compact, title_font, body_font, prose_font = self._card_typography(rect, enemy, wide)
        pad = 7 if compact else 12
        x, y = rect.x + pad, rect.y + (6 if compact else 10)
        width = rect.w - pad * 2
        details_x = x
        details_width = width
        title_width = round(width * 0.44) if wide else width
        y = self._paragraph(surface, enemy.name, (x, y), title_width, BONE if alive else MUTED, font=title_font)
        y += 1 if compact else 4
        y = self._paragraph(surface, self._health_label(enemy), (x, y), title_width, RED if alive else MUTED, font=body_font)
        y += 1 if compact else 4
        self._health(surface, pg.Rect(x, y, title_width, 3 if compact else 5), enemy.hp, enemy.max_hp)
        y += 6 if compact else 11
        y = self._paragraph(surface, self._armor_label(enemy), (x, y), title_width, MUTED, font=body_font)
        y += 2 if compact else 6
        if wide:
            self._status_line(surface, enemy.statuses, x, y, title_width, font=body_font)
            details_x = x + title_width + 22
            details_width = width - title_width - 22
            y = rect.y + (6 if compact else 10)
            pg.draw.line(surface, EDGE, (details_x - 11, rect.y + 12), (details_x - 11, rect.bottom - 12))
        if not alive:
            self._text(surface, "FALLEN", (details_x, y + 3), MUTED, font=title_font)
            return
        intent_y = y
        y = self._paragraph(surface, enemy.intent_label.upper(), (details_x, y), details_width, AMBER, font=title_font)
        y += 1 if compact else 3
        damage = self._damage_label(enemy)
        y = self._paragraph(surface, damage, (details_x, y), details_width, RED if enemy.damage_max else MUTED, font=body_font)
        y += 2 if compact else 5
        y = self._paragraph(surface, enemy.telegraph, (details_x, y), details_width, MUTED, font=prose_font)
        y += 3 if compact else 6
        interrupt_color = TEAL if enemy.interruptible else AMBER if self.snapshot and self.snapshot.defensive_objective else MUTED
        y = self._paragraph(surface, self._interrupt_label(enemy), (details_x, y), details_width, interrupt_color, font=body_font)
        y += 2 if compact else 6
        self.tooltip_hits.append((pg.Rect(details_x, intent_y, details_width, max(20, y - intent_y)), f"{enemy.intent_label}: {enemy.telegraph}\n{enemy.threat}" + ("\nPower Attack or Mara can interrupt this intent." if enemy.interruptible else "") + "\nDamage is a forecast before your move. Defend, Power Attack, and interruptions can change it."))
        if not wide:
            self._status_line(surface, enemy.statuses, details_x, y, details_width, font=body_font)

    def _draw_feedback(self, surface: Any) -> None:
        pg = self.pg
        stacked: dict[str, int] = {}
        for effect in self._effects:
            if effect.age < 0:
                continue
            feedback = effect.feedback
            position = self.actor_positions.get(feedback.target_id) or self.actor_positions.get(feedback.actor_id)
            if position is None:
                continue
            x, ground = position
            labels = {"defend": "GUARDED", "evade": "EVADED", "interrupt": "INTERRUPTED", "fallen": "FALLEN"}
            if feedback.kind == "damage":
                text, color = (f"−{feedback.amount}", RED) if feedback.amount else ("BLOCKED", TEAL)
            elif feedback.kind == "heal":
                text, color = f"+{feedback.amount}", TEAL
            else:
                text, color = labels.get(feedback.kind, feedback.kind.upper()), AMBER
            font = self.number_font if feedback.kind in ("damage", "heal") else self.small_font
            glyph = font.render(text, True, color)
            rise = 0 if self._reduced_motion else int(min(1.0, effect.age) * 25)
            stack = stacked.get(feedback.target_id, 0)
            stacked[feedback.target_id] = stack + 1
            bottom = ground - 102 - rise - stack * 25
            if self._arena_rect.h < 120:
                bottom = self._arena_rect.y + glyph.get_height() + 5 + stack * 23
            pos = glyph.get_rect(midbottom=(x, bottom))
            label = pos.inflate(12, 6)
            pg.draw.rect(surface, INK, label)
            pg.draw.rect(surface, EDGE, label, 1)
            surface.blit(glyph, pos)
            if feedback.kind == "defend" and not self._reduced_motion and effect.age < 0.45:
                pg.draw.arc(surface, TEAL, (x - 26, ground - 88, 52, 80), -math.pi / 2, math.pi / 2, 2)

    def _draw_tooltip(self, surface: Any) -> None:
        if self._mouse is None:
            return
        text = next((text for rect, text in reversed(self.tooltip_hits) if rect.collidepoint(self._mouse)), None)
        if not text:
            return
        width = min(320, max(170, self._rect.w - 32))
        lines = [line for paragraph in text.splitlines() for line in _wrapped(paragraph, self.small_font, width - 20)]
        height = len(lines) * self.small_font.get_linesize() + 16
        x = max(self._rect.x + 8, min(self._mouse[0] + 12, self._rect.right - width - 8))
        y = max(self._rect.y + 4, min(self._mouse[1] - height - 10, self._rect.bottom - height - 4))
        rect = self.pg.Rect(x, y, width, height)
        self.pg.draw.rect(surface, INK, rect)
        self.pg.draw.rect(surface, AMBER, rect, 1)
        for line in lines:
            self._text(surface, line, (x + 10, y + 8), BONE, font=self.small_font)
            y += self.small_font.get_linesize()

    def draw(self, surface: Any, rect: Any, now_ms: int = 0) -> Any:
        """Draw the arena and full intent cards inside ``rect`` and return it."""
        pg = self.pg
        rect = pg.Rect(rect)
        self._rect = rect.copy()
        self.enemy_hits.clear()
        self.sprite_hits.clear()
        self.tooltip_hits.clear()
        self.actor_positions.clear()
        self.actor_positions.clear()
        if self.snapshot is None or rect.w <= 0 or rect.h <= 0:
            return rect
        snapshot = self.snapshot
        previous_clip = surface.get_clip()
        surface.set_clip(rect.clip(previous_clip))
        pg.draw.rect(surface, INK, rect)
        label = {"active": "CHOOSE YOUR MOVE", "victory": "THE ROAD IS YOURS", "defeat": "THE SHADOW PREVAILS", "escaped": "YOU FOUND A WAY OUT"}.get(snapshot.phase, snapshot.phase.upper())
        self._text(surface, f"ROUND {snapshot.round_number}" + (f" / {snapshot.max_rounds}" if snapshot.max_rounds else ""), (rect.x + 12, rect.y + 9), AMBER, font=self.banner_font)
        phase_width = self.small_font.size(label)[0]
        self._text(surface, label, (rect.right - phase_width - 12, rect.y + 13), TEAL if snapshot.phase == "victory" else MUTED, font=self.small_font)
        header_bottom = rect.y + 34
        objective = snapshot.objective or ("Read their intent. Choose your target. Survive the road." if snapshot.phase == "active" else "")
        if objective:
            header_bottom = self._paragraph(surface, objective, (rect.x + 12, header_bottom), rect.w - 24, BONE, font=self.small_font) + 7
        compact = rect.h < 390
        if compact:
            card_height = min(172, max(104, rect.bottom - header_bottom - 72))
            cards_y = rect.bottom - card_height
        else:
            card_height = min(218, max(180, round(rect.h * 0.45)))
            cards_y = max(header_bottom + 110, rect.bottom - card_height)
        arena = pg.Rect(rect.x + 1, header_bottom, rect.w - 2, max(1, cards_y - header_bottom - 8))
        self._arena_rect = arena.copy()
        self._draw_backdrop(surface, arena)
        surface.set_clip(arena.clip(previous_clip))
        # Keep environmental motion slow, sparse, and deterministic. Reduced
        # motion removes both these drifting embers and actor displacement.
        if not self._reduced_motion:
            for index in range(9):
                px = arena.x + int((index * 71 + now_ms * (0.007 + index % 3 * 0.002)) % max(1, arena.w))
                py = arena.y + int((index * 29 - now_ms * 0.009) % max(1, arena.h - 20))
                pg.draw.rect(surface, (96, 84, 59) if index % 3 else (133, 108, 65), (px, py, 2, 2))
        ground = arena.bottom - (16 if compact else 25)
        actor_scale = 2 if arena.h >= 116 and arena.w >= 400 else 1
        player_x = arena.x + max(65, round(arena.w * 0.19))
        self._draw_actor(surface, "player", "player", (player_x, ground), actor_scale, facing_left=False, alive=snapshot.player.hp > 0, now_ms=now_ms)
        player_label = snapshot.player.name
        self._text(surface, player_label, (player_x - self.small_font.size(player_label)[0] // 2, ground + 3), BONE, font=self.small_font)
        # Companions stand a step behind the traveler rather than becoming
        # abstract ability names in a menu.
        for index, companion in enumerate(tuple(companion for companion in snapshot.companions if companion.available)[:2]):
            ally_x = max(arena.x + 18, player_x - (35 if actor_scale == 1 else 53) - index * (24 if actor_scale == 1 else 30))
            self._draw_actor(surface, companion.id, self._kind(companion.id + companion.name), (ally_x, ground - 4 - index * 3), 0.65 if actor_scale == 1 else 1, facing_left=False, now_ms=now_ms)
        enemies = snapshot.enemies
        enemy_left = arena.x + round(arena.w * 0.50)
        enemy_span = max(1, arena.right - 35 - enemy_left)
        for index, enemy in enumerate(enemies):
            enemy_x = enemy_left + round(enemy_span * ((index + 0.5) / max(1, len(enemies))))
            self._draw_actor(surface, enemy.id, self._kind(enemy.archetype + " " + enemy.name), (enemy_x, ground), actor_scale, facing_left=True, alive=enemy.hp > 0, targeted=enemy.id == snapshot.target_id, now_ms=now_ms)
            if enemy.hp > 0:
                self._health(surface, pg.Rect(enemy_x - 23, ground + 5, 46, 3), enemy.hp, enemy.max_hp)
                number = str(index + 1)
                number_pos = (enemy_x - 34, ground + 1) if compact else (enemy_x - 3, ground + 10)
                self._text(surface, number, number_pos, AMBER if enemy.id == snapshot.target_id else MUTED, font=self.mini_font if compact else self.small_font)
        self._draw_feedback(surface)
        # Player conditions remain visible even when a long transcript scrolls.
        self._arena_conditions(surface, arena)
        surface.set_clip(rect.clip(previous_clip))
        gap = 8
        count = max(1, len(enemies))
        usable_width = rect.w - gap * (count - 1)
        for index, enemy in enumerate(enemies):
            left = rect.x + round(usable_width * index / count) + gap * index
            right = rect.x + round(usable_width * (index + 1) / count) + gap * index
            card = pg.Rect(left, cards_y, right - left, rect.bottom - cards_y)
            self._draw_card(surface, card, enemy, wide=count == 1 and card.w >= 390)
        self._draw_tooltip(surface)
        surface.set_clip(previous_clip)
        return rect
