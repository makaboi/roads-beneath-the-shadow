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
from .pixel_theme import load_font
from .pixel_world import hero_sprite_name, motion_frame_rect


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
    duration: float = 1.25
    cue_emitted: bool = False

    @property
    def impact_time(self) -> float:
        return 0.18 if self.feedback.kind in {"damage", "evade"} and self.feedback.actor_id != self.feedback.target_id else 0.0


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

    TYPICAL_TURN_DURATION = 0.73
    MAX_TURN_DURATION = 1.35
    REDUCED_MOTION_TURN_DURATION = 0.32

    def __init__(self, pg: Any) -> None:
        self.pg = pg
        self.snapshot: CombatSnapshot | None = None
        self.font = load_font(pg, 13)
        self.bold_font = load_font(pg, 13, bold=True)
        self.compact_bold_font = load_font(pg, 12, bold=True)
        self.mini_bold_font = load_font(pg, 10, bold=True)
        self.mini_font = load_font(pg, 10)
        self.mini_prose_font = load_font(pg, 10)
        self.small_font = load_font(pg, 11)
        self.party_font = load_font(pg, 9)
        self.banner_font = load_font(pg, 16, bold=True)
        self.number_font = load_font(pg, 19, bold=True)
        self.compact_number_font = load_font(pg, 15, bold=True)
        self.enemy_hits: list[tuple[Any, str]] = []
        self.sprite_hits: list[tuple[Any, str]] = []
        self.actor_positions: dict[str, tuple[int, int]] = {}
        self.actor_rects: dict[str, Any] = {}
        self.party_hits: list[tuple[Any, str]] = []
        self.condition_hits: list[tuple[Any, str]] = []
        self.feedback_rects: list[Any] = []
        self.feedback_labels: list[tuple[str, str, Any]] = []
        self.target_marker_rect: Any = None
        self.tooltip_rect: Any = None
        self.hovered_id: str | None = None
        self.hovered_actor_id: str | None = None
        self.tooltip_hits: list[tuple[Any, str]] = []
        self._mouse: tuple[int, int] | None = None
        self._effects: list[_Effect] = []
        self._cues: list[str] = []
        self._sprites: dict[tuple[Any, ...], Any] = {}
        self._fitted_fonts: dict[tuple[int, float], Any] = {}
        self._typography_cache: dict[tuple[Any, ...], tuple[bool, Any, Any, Any]] = {}
        self._tooltip_layout_cache: dict[tuple[Any, ...], tuple[Any, list[str], int, int]] = {}
        self._character_atlas: Any = None
        self._motion_atlas: Any = None
        self._atlas_checked = False
        self._backdrops: dict[str, Any] = {}
        self._scaled_backdrop: tuple[Any, tuple[int, int], Any] | None = None
        self._scene_override: str | Any | None = None
        self._rect = pg.Rect(0, 0, 0, 0)
        self._arena_rect = pg.Rect(0, 0, 0, 0)
        self._reduced_motion = False
        self._time = 0.0
        self._health_trails: dict[str, float] = {}
        self._health_targets: dict[str, int] = {}
        self._health_ages: dict[str, float] = {}

    def set_snapshot(self, snapshot: CombatSnapshot | None) -> None:
        """Replace presentation data without retaining mutable engine objects."""
        self._typography_cache.clear()
        if snapshot is not None:
            entities = [("player", snapshot.player.hp), *((enemy.id, enemy.hp) for enemy in snapshot.enemies)]
            new_encounter = self.snapshot is None or snapshot.phase == "active" and snapshot.round_number == 1 and self.snapshot.phase != "active"
            if new_encounter:
                self._health_trails.clear()
                self._health_targets.clear()
                self._health_ages.clear()
            for actor_id, hp in entities:
                previous_hp = self._health_targets.get(actor_id, hp)
                if hp != previous_hp:
                    self._health_trails[actor_id] = max(float(previous_hp), self._health_trails.get(actor_id, float(previous_hp)), float(hp))
                    self._health_ages[actor_id] = 0.0
                else:
                    self._health_trails.setdefault(actor_id, float(hp))
                self._health_targets[actor_id] = hp
        if snapshot is None:
            self._effects.clear()
            self._cues.clear()
            self.enemy_hits.clear()
            self.sprite_hits.clear()
            self.actor_positions.clear()
            self.actor_rects.clear()
            self.party_hits.clear()
            self.condition_hits.clear()
            self.feedback_rects.clear()
            self.feedback_labels.clear()
            self.target_marker_rect = None
            self.tooltip_rect = None
            self.hovered_id = None
            self.hovered_actor_id = None
            self._health_trails.clear()
            self._health_targets.clear()
            self._health_ages.clear()
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
        if self._effects and not self.has_pending_feedback:
            # The next committed move starts a fresh result group. Otherwise
            # lingering labels could add last round's damage into this round.
            self._effects.clear()
            self._cues.clear()
        # A whole resolved turn arrives in one queue drain. Stagger its visual
        # hits so each attacker and damage amount can be read independently.
        spacing, maximum = (0.05, 0.16) if self._reduced_motion else (0.18, 0.80)
        delay = max(0.0, min(maximum, spacing - self._effects[-1].age)) if self._effects else 0.0
        self._effects.append(_Effect(feedback, age=-delay))

    @property
    def resolving(self) -> bool:
        """True while a queued action still has a visible impact to resolve."""
        return self.has_pending_feedback

    @property
    def has_pending_feedback(self) -> bool:
        """Gate paid actions only until impacts land, rather than popup expiry.

        A common attack/exchange takes 0.73 seconds; even a busy formation is
        bounded to 1.35 seconds. Reduced motion resolves within 0.32 seconds.
        Inspecting or changing targets can remain available throughout.
        """
        cutoff = 0.16 if self._reduced_motion else 0.55
        return any(effect.age < cutoff for effect in self._effects)

    @property
    def busy(self) -> bool:
        return self.has_pending_feedback

    def drain_cues(self) -> tuple[str, ...]:
        """Consume audio cues once, when their visible effects actually land.

        The window owns audio and user volume preferences. This bounded queue
        stays safe even when a frontend chooses to render without sound.
        """
        cues = tuple(self._cues)
        self._cues.clear()
        return cues

    def update(self, dt: float, reduced_motion: bool = False) -> None:
        if reduced_motion and not self._reduced_motion:
            for effect in self._effects:
                if effect.age < 0:
                    effect.age = max(-0.16, effect.age * 0.25)
        self._reduced_motion = bool(reduced_motion)
        dt = max(0.0, float(dt))
        self._time += dt
        for effect in self._effects:
            effect.age += dt
            impact = 0 if self._reduced_motion else effect.impact_time
            if not effect.cue_emitted and impact <= effect.age < effect.duration:
                feedback = effect.feedback
                cue = {"heal": "heal", "defend": "guard", "evade": "evade", "interrupt": "interrupt", "fallen": "fall", "escape": "escape"}.get(feedback.kind)
                if feedback.kind == "damage":
                    cue = "block" if feedback.amount == 0 else "hurt" if feedback.actor_id == feedback.target_id else "hit"
                if cue:
                    self._cues.append(cue)
                    self._cues[:] = self._cues[-16:]
                effect.cue_emitted = True
        self._effects[:] = [effect for effect in self._effects if effect.age < effect.duration]
        for actor_id, hp in self._health_targets.items():
            self._health_ages[actor_id] = self._health_ages.get(actor_id, 0.0) + dt
            trail = self._health_trails.get(actor_id, float(hp))
            pending_hit = any(effect.feedback.kind == "damage" and effect.feedback.target_id == actor_id and effect.age < effect.impact_time for effect in self._effects)
            if self._reduced_motion:
                trail = float(hp)
            elif self._health_ages[actor_id] > 0.22 and not pending_hit:
                trail = hp + (trail - hp) * math.exp(-dt * 6.0)
                if abs(trail - hp) < 0.05:
                    trail = float(hp)
            self._health_trails[actor_id] = trail

    def handle_event(self, event: Any) -> tuple[bool, str | None]:
        if self.snapshot is None:
            return False, None
        if event.type == self.pg.MOUSEMOTION:
            self._mouse = tuple(event.pos)
            self.hovered_id = next(
                (enemy_id for rect, enemy_id in self.enemy_hits + self.sprite_hits if rect.collidepoint(event.pos)), None
            )
            self.hovered_actor_id = next((actor_id for rect, actor_id in self.party_hits if rect.collidepoint(event.pos)), None)
            return False, None
        if event.type in {getattr(self.pg, "WINDOWLEAVE", -1), getattr(self.pg, "WINDOWFOCUSLOST", -2)}:
            self._mouse = None
            self.hovered_id = None
            self.hovered_actor_id = None
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

    def _sprite(self, kind: str, facing_left: bool, pose: int = 0, *, animation_frame: int = 0, stance: str = "idle") -> Any:
        if kind not in {"player", "mara", "tobin"}:
            animation_frame, stance = 0, "idle"
        weapon = self._weapon_style() if kind == "player" else ""
        identity = hero_sprite_name(self.snapshot.player.origin) if kind == "player" and self.snapshot else kind
        key = (kind, identity, weapon, facing_left, pose, animation_frame % 8, stance)
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
            try:
                self._motion_atlas = pg.image.load(str(ASSET_DIR / "world-motion.png"))
            except (OSError, pg.error):
                pass
        # The traveler and companions share their exact coats and silhouettes
        # with the exploration maps. Original encounter creatures follow the
        # same palette while keeping different weapons and body shapes.
        atlas_rows = {"player": 2, "mara": 4, "tobin": 5}
        if (self._motion_atlas is not None or self._character_atlas is not None) and kind in atlas_rows:
            if self._motion_atlas is not None:
                native = self._motion_atlas.subsurface(pg.Rect(motion_frame_rect(identity, direction=2, frame=animation_frame, pose=stance)))
            else:
                native = self._character_atlas.subsurface(pg.Rect((2 if pose else 0) * 20, atlas_rows[kind] * 24, 20, 24))
            sprite = pg.transform.scale(native, (40, 48))
            if kind == "tobin":
                pg.draw.lines(sprite, AMBER, False, [(29, 15), (33, 21), (34, 27), (32, 34), (28, 37)], 1)
                pg.draw.line(sprite, MUTED, (29, 15), (28, 37))
            else:
                if kind == "player" and weapon == "staff":
                    staff_start = (18, 28) if pose > 1 else (29, 39)
                    staff_tip = (38, 29) if pose > 1 else (33, 12) if pose else (29, 13)
                    pg.draw.line(sprite, (129, 105, 68), staff_start, staff_tip, 2)
                    pg.draw.line(sprite, BONE, staff_tip, (min(39, staff_tip[0] + 2), staff_tip[1]))
                elif kind == "player" and weapon == "unarmed":
                    fist_x = 33 if pose > 1 else 29 if pose else 28
                    pg.draw.line(sprite, (193, 160, 119), (25, 27), (fist_x, 28), 2)
                    pg.draw.rect(sprite, (193, 160, 119), (fist_x, 27, 3, 3))
                else:
                    tip = (34, 34) if pose > 1 else (30, 21) if weapon == "knife" and pose else (32, 23) if weapon == "knife" else (35, 17 if pose else 21)
                    pg.draw.line(sprite, BONE, (28, 29), tip, 1)
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
            silhouette = ([(2, 31), (10, 26), (17, 24), (27, 25), (31, 20), (34, 22), (37, 29), (39, 32), (39, 39), (34, 39), (28, 36), (22, 38), (17, 37), (13, 43), (9, 43), (9, 37), (4, 36)]
                          if pose else [(2, 31), (10, 26), (17, 24), (27, 25), (31, 20), (34, 23), (37, 30), (40, 34), (34, 38), (32, 45), (28, 45), (27, 37), (16, 37), (13, 45), (9, 45), (10, 36), (4, 36)])
            pg.draw.polygon(sprite, SHADOW, silhouette)
            pg.draw.polygon(sprite, fur, [(4, 31), (12, 28), (24, 27), (31, 28), (34, 24), (35, 31), (38, 33), (34, 36), (28, 35), (15, 35), (8, 34)])
            box(lit, (13, 28, 12, 2))
            box((95, 88, 73), (22, 29, 9, 4))
            box(AMBER, (34, 31, 2, 1))
            if pose:
                # A pounce reaches with the forepaws and opens the jaw;
                # the silhouette changes before the dash reaches its target.
                pg.draw.lines(sprite, fur, False, [(12, 35), (10, 39), (10, 41)], 3)
                pg.draw.lines(sprite, fur, False, [(27, 34), (33, 37), (37, 37)], 3)
                box(BONE, (37, 37, 2, 1))
                box(SHADOW, (34, 34, 5, 3))
                box((139, 70, 61), (35, 35, 3, 2))
                box(BONE, (35, 34, 1, 2))
                box(BONE, (38, 36, 1, 1))
            else:
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
                if pose > 1:
                    pg.draw.line(sprite, (117, 95, 65), (27, 25), (36, 31), 3)
                    box(skin, (28, 25, 3, 4))
                    pg.draw.polygon(sprite, (139, 127, 105), [(35, 26), (39, 29), (39, 36), (32, 33)])
                    pg.draw.line(sprite, (72, 65, 54), (36, 28), (38, 30), 2)
                elif pose:
                    pg.draw.line(sprite, (117, 95, 65), (27, 28), (33, 9), 3)
                    box(skin, (28, 22, 3, 4))
                    pg.draw.polygon(sprite, (139, 127, 105), [(29, 6), (37, 8), (35, 16), (27, 13)])
                    pg.draw.line(sprite, (72, 65, 54), (30, 8), (35, 9), 2)
                else:
                    box((117, 95, 65), (29, 17, 3, 25))
                    box((139, 127, 105), (26, 14, 9, 8))
                    box((72, 65, 54), (27, 15, 6, 2))
            elif kind == "rider":
                box((156, 149, 133), (28, 13, 2, 24))
                box((204, 196, 158), (29, 13, 1, 21))
            else:
                blade_y = 33 if pose > 1 else 14 if pose else 20
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

    def _weapon_style(self) -> str:
        weapon = self.snapshot.player.weapon_id if self.snapshot else "sword"
        if weapon is None:
            return "unarmed"
        if "staff" in weapon:
            return "staff"
        if any(word in weapon for word in ("knife", "dagger", "dirk")):
            return "knife"
        return "sword"

    def _active_effects(self, actor_id: str) -> list[_Effect]:
        return [effect for effect in self._effects if (0 if self._reduced_motion else effect.impact_time) <= effect.age < effect.duration and effect.feedback.target_id == actor_id]

    def _fall_progress(self, actor_id: str, alive: bool) -> float:
        """A final snapshot cannot turn an actor into a corpse before its hit."""
        if alive:
            return 0.0
        fallen = next((effect for effect in self._effects if effect.feedback.kind == "fallen" and effect.feedback.target_id == actor_id), None)
        if fallen is None or self._reduced_motion:
            return 1.0
        return min(1.0, max(0.0, fallen.age) / 0.22)

    def _draw_actor(self, surface: Any, actor_id: str, kind: str, anchor: tuple[int, int], scale: float, *, facing_left: bool, alive: bool = True, targeted: bool = False, now_ms: int = 0) -> None:
        pg = self.pg
        x, ground = anchor
        self.actor_positions[actor_id] = anchor
        effects = self._active_effects(actor_id)
        outgoing = next((effect for effect in self._effects if 0 <= effect.age < 0.30 and effect.feedback.actor_id == actor_id and effect.feedback.kind in {"damage", "evade"} and effect.feedback.target_id != actor_id), None)
        offset = 0
        bob = 0
        fall = self._fall_progress(actor_id, alive)
        standing = fall < 1
        if not self._reduced_motion and standing:
            if kind not in {"player", "mara", "tobin"}:
                bob = int(math.sin(now_ms / 390 + x / 45) > 0)
            if outgoing and kind not in {"tobin", "archer"}:
                target = self.actor_positions.get(outgoing.feedback.target_id)
                if target is not None:
                    travel = target[0] - x
                    reach = max(0, abs(travel) - round(34 * scale)) * (1 if travel > 0 else -1)
                    # Return before the formation's next impact. Longer
                    # returns let a later attacker cover the previous target
                    # and strike while the traveler is still across the arena.
                    progress = outgoing.age / 0.18 if outgoing.age < 0.18 else max(0.0, 1 - (outgoing.age - 0.18) / 0.12)
                    offset = round(reach * (1 - (1 - min(1.0, progress)) ** 2))
            hit = next((effect for effect in reversed(effects) if effect.feedback.kind == "damage" and effect.feedback.amount > 0 and effect.age - effect.impact_time < 0.18), None)
            if hit is not None:
                offset += round((2 if int((hit.age - hit.impact_time) * 50) % 2 else -2) * max(1, scale))
            evasion = next((effect for effect in self._effects if effect.feedback.kind == "evade" and effect.feedback.target_id == actor_id and 0 <= effect.age < 0.36), None)
            if evasion is not None:
                offset -= round(math.sin(evasion.age / 0.36 * math.pi) * 10 * max(0.75, scale))
        escape = next((effect for effect in self._effects if effect.feedback.kind == "escape" and 0 <= effect.age < effect.duration), None)
        escaped = bool(self.snapshot and self.snapshot.phase == "escaped")
        escape_progress = 1.0 if escaped and (self._reduced_motion or escape is None) else min(1.0, escape.age / 0.45) if escape is not None else 0.0
        if actor_id in {"player", "mara", "tobin"} and escape_progress >= 1:
            return
        if actor_id in {"player", "mara", "tobin"} and escape_progress and not self._reduced_motion:
            offset -= round(self._arena_rect.w * 0.24 * escape_progress)
        shadow_width = int((35 if kind == "warg" else 27) * scale)
        pg.draw.ellipse(surface, SHADOW, (x + offset - shadow_width // 2, ground - 6, shadow_width, 10))
        if targeted and alive:
            pg.draw.ellipse(surface, AMBER, (x + offset - shadow_width // 2 - 5, ground - 8, shadow_width + 10, 13), 2)
        guarding = any(effect.feedback.kind == "defend" and effect.age < 0.5 for effect in effects) or any(effect.feedback.kind == "defend" and effect.feedback.actor_id == actor_id and 0 <= effect.age < 0.5 for effect in self._effects)
        stance = "walk" if outgoing and kind != "tobin" else "guard" if guarding else "idle"
        frame = 0 if self._reduced_motion else int(outgoing.age * 30) % 8 if outgoing else int(now_ms * 0.0016) % 8
        attack_pose = (2 if outgoing.age >= outgoing.impact_time else 1) if outgoing else 0
        sprite = self._sprite(kind, facing_left, attack_pose, animation_frame=frame, stance=stance)
        if actor_id in {"player", "mara", "tobin"} and escape_progress and not self._reduced_motion:
            sprite = sprite.copy()
            sprite.set_alpha(round(255 * (1 - escape_progress)))
        if fall:
            sprite = pg.transform.rotate(sprite, round((90 if facing_left else -90) * fall))
            sprite = sprite.copy()
            sprite.set_alpha(round(255 - 165 * fall))
        sprite = pg.transform.scale(sprite, (max(1, int(sprite.get_width() * scale)), max(1, int(sprite.get_height() * scale))))
        sprite_rect = sprite.get_rect(midbottom=(x + offset, ground - bob))
        self.actor_rects[actor_id] = sprite_rect.copy()
        surface.blit(sprite, sprite_rect)
        if standing and not self._reduced_motion and any(effect.feedback.kind == "damage" and effect.feedback.amount > 0 and effect.age - effect.impact_time < 0.12 for effect in effects):
            flash = pg.Surface(sprite.get_size(), pg.SRCALPHA)
            flash.blit(sprite, (0, 0))
            # Multiply only existing pixels so no rectangular box flashes
            # around a sparse pixel silhouette.
            flash.fill((*RED, 255), special_flags=pg.BLEND_RGBA_MULT)
            flash.set_alpha(160)
            surface.blit(flash, sprite_rect)
        if standing:
            for effect in effects:
                age = effect.age - (0 if self._reduced_motion else effect.impact_time)
                if effect.feedback.kind == "phase" and age < 0.6 and not self._reduced_motion:
                    spread = round(3 + age * 10)
                    for dx, dy in ((-1, -1), (1, -1), (-1, 0), (1, 0)):
                        spark = (sprite_rect.centerx + dx * (sprite_rect.w // 2 + spread), sprite_rect.centery + dy * (sprite_rect.h // 3 + spread))
                        pg.draw.rect(surface, AMBER if age < 0.3 else RED, (*spark, 2, 3))
                elif effect.feedback.kind in {"defend", "evade"} and age < 0.5:
                    guard = sprite_rect.inflate(10, 4).clip(self._arena_rect)
                    pg.draw.arc(surface, TEAL, guard, -math.pi / 2, math.pi / 2, 2)
                    pg.draw.line(surface, TEAL, (guard.centerx, guard.y), (guard.right - 2, guard.y + 3), 1)
                elif effect.feedback.kind == "heal" and age < 0.7:
                    center = (sprite_rect.centerx, sprite_rect.centery)
                    pg.draw.line(surface, TEAL, (center[0] - 4, center[1]), (center[0] + 4, center[1]), 2)
                    pg.draw.line(surface, TEAL, (center[0], center[1] - 4), (center[0], center[1] + 4), 2)
        if actor_id == "player" or actor_id in {"mara", "tobin"}:
            self.party_hits.append((sprite_rect.inflate(8, 6).clip(self._arena_rect), actor_id))
            self.tooltip_hits.append((self.party_hits[-1][0], self._party_help(actor_id)))
        if actor_id.startswith("enemy_"):
            self.sprite_hits.append((sprite_rect.inflate(12, 12).clip(self._arena_rect), actor_id))
            enemy = next((enemy for enemy in self.snapshot.enemies if enemy.id == actor_id), None) if self.snapshot else None
            if enemy is not None:
                defense = "Cannot be wounded" if enemy.invulnerable else f"Health {enemy.hp}/{enemy.max_hp}"
                help_text = f"{enemy.name}\n{defense} · Armor {enemy.armor}\n" + (self._intent_help(enemy) if alive else "This foe has fallen.")
                self.tooltip_hits.append((self.sprite_hits[-1][0], help_text))
            if targeted and alive:
                marker_x = sprite_rect.centerx
                marker_y = max(self._arena_rect.y + 1, sprite_rect.y - 9)
                self.target_marker_rect = pg.Rect(marker_x - 5, marker_y, 11, 7)
                pg.draw.polygon(surface, AMBER, [(marker_x - 5, marker_y), (marker_x + 5, marker_y), (marker_x, marker_y + 6)])

    def _health(self, surface: Any, rect: Any, hp: int, maximum: int, *, color: tuple[int, int, int] = RED, actor_id: str | None = None) -> None:
        pg = self.pg
        pg.draw.rect(surface, (43, 45, 44), rect)
        trail = self._health_trails.get(actor_id, float(hp)) if actor_id else float(hp)
        if maximum > 0 and trail > hp:
            lost = rect.copy()
            lost.w = max(1, round(rect.w * min(1, trail / maximum)))
            pg.draw.rect(surface, AMBER, lost)
        if maximum > 0 and hp > 0:
            fill = rect.copy()
            fill.w = max(1, round(rect.w * min(1, hp / maximum)))
            pg.draw.rect(surface, color, fill)
            pg.draw.line(surface, tuple(min(255, channel + 20) for channel in color), fill.topleft, (fill.right - 1, fill.y))

    def _protected_meter(self, surface: Any, rect: Any) -> None:
        self.pg.draw.rect(surface, (54, 47, 35), rect)
        for x in range(rect.x + 2, rect.right - 1, 8):
            self.pg.draw.line(surface, AMBER, (x, rect.y), (min(x + 2, rect.right - 1), rect.bottom - 1))

    def _status_line(self, surface: Any, statuses: Any, x: int, y: int, width: int, *, font: Any = None) -> int:
        text = "  ".join(f"{status.label} {status.remaining}" for status in statuses)
        if not text:
            return y
        start = y
        y = self._paragraph(surface, text, (x, y), width, TEAL, font=font or self.small_font)
        description = "\n".join(f"{status.label}: {status.description}" for status in statuses)
        self.tooltip_hits.append((self.pg.Rect(x, start, width, y - start), description))
        return y

    def _header_conditions(self, surface: Any, rect: Any) -> int:
        """Status badges live outside the actor/impact plane, even when short."""
        if self.snapshot is None or not self.snapshot.player.statuses:
            return rect.y
        x, y = rect.x, rect.y
        bottom = y
        for status in self.snapshot.player.statuses:
            label = f"{status.label} {status.remaining}"
            lines = _wrapped(label, self.mini_font, max(1, rect.w - 10))
            width = min(rect.w, max(self.mini_font.size(line)[0] for line in lines) + 10)
            height = len(lines) * self.mini_font.get_linesize() + 4
            if x > rect.x and x + width > rect.right:
                x, y = rect.x, bottom + 3
            badge = self.pg.Rect(x, y, width, height)
            color = RED if status.id in {"bleeding", "exposed"} else TEAL
            self.pg.draw.rect(surface, PANEL, badge)
            self.pg.draw.rect(surface, color, badge, 1)
            for index, line in enumerate(lines):
                self._text(surface, line, (x + 5, y + 2 + index * self.mini_font.get_linesize()), color, font=self.mini_font)
            self.condition_hits.append((badge, status.id))
            self.tooltip_hits.append((badge, f"{status.label}: {status.description}"))
            x += width + 5
            bottom = max(bottom, badge.bottom)
        return bottom

    def _party_help(self, actor_id: str) -> str:
        if self.snapshot is None:
            return ""
        if actor_id == "player":
            player = self.snapshot.player
            lines = [player.name, f"Health {player.hp}/{player.max_hp} · Focus {player.focus}/{player.max_focus}",
                     f"{player.weapon_name} · Armor {player.armor}"]
            lines.extend(f"{status.label}: {status.description}" for status in player.statuses)
            return "\n".join(lines)
        companion = next((ally for ally in self.snapshot.companions if ally.id == actor_id), None)
        if companion is None:
            return ""
        lines = [f"{companion.name} · Bond {companion.trust}"]
        commands = [action for action in self.snapshot.actions if action.id.startswith(actor_id)]
        for action in commands:
            label = action.label.split(" (", 1)[0]
            lines.append(f"{label} · {action.focus_cost} Focus")
            lines.append(action.description)
            if not action.enabled:
                lines.append(action.disabled_reason)
        if not commands:
            lines.append("Your companion stands beside you.")
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _damage_label(enemy: Any) -> str:
        if enemy.damage_max or enemy.threat in {"attack", "danger"}:
            return f"{enemy.damage_min}–{enemy.damage_max} DAMAGE"
        return {"setup": "PREPARING", "mark": "SHADOW EFFECT"}.get(enemy.threat, str(enemy.threat).upper())

    @staticmethod
    def _status_text(statuses: Any) -> str:
        return "  ".join(f"{status.label} {status.remaining}" for status in statuses)

    def _health_label(self, enemy: Any) -> str:
        if enemy.invulnerable:
            rounds = self.snapshot.max_rounds if self.snapshot else None
            survival = f"\n{'HELD' if self.snapshot and self.snapshot.phase == 'victory' else 'SURVIVE'} {rounds} ROUNDS" if rounds else ""
            return "CANNOT BE WOUNDED" + survival
        return f"{max(0, enemy.hp)} / {enemy.max_hp} HEALTH"

    @staticmethod
    def _armor_label(enemy: Any) -> str:
        return f"ARMOR {enemy.armor}" + (f"  •  PHASE {enemy.phase}" if enemy.phase > 1 else "")

    def _interrupt_label(self, enemy: Any) -> str:
        if self.snapshot and self.snapshot.defensive_objective:
            return "◇ HOLD YOUR GROUND"
        if enemy.interruptible:
            available = any(action.enabled and action.id in {"power", "mara"} for action in self.snapshot.actions) if self.snapshot else False
            return "◆ CAN INTERRUPT" if available else "◆ INTERRUPTIBLE"
        return "◇ COMMITTED INTENT"

    def _intent_help(self, enemy: Any) -> str:
        lines = [f"{enemy.intent_label}: {enemy.telegraph}"]
        if enemy.damage_max or enemy.threat in {"attack", "danger"}:
            lines.append(f"Current stance: {enemy.damage_min}–{enemy.damage_max} Health damage. Defend and new effects can change this forecast.")
        elif enemy.threat == "setup":
            lines.append("Preparation: no immediate physical damage.")
        elif enemy.threat == "mark":
            lines.append("A shadow effect drains Focus and leaves you Exposed.")
        if self.snapshot and self.snapshot.defensive_objective:
            guards = [action.label.split(" (", 1)[0] for action in self.snapshot.actions if action.enabled and action.id in {"defend", "origin", "mara_guard", "tobin_guard"}]
            choices = ", ".join(guards[:-1]) + " or " + guards[-1] if len(guards) > 1 else guards[0] if guards else "Guard"
            lines.append(f"Survival objective: {choices}. You cannot harm this foe here.")
        elif enemy.interruptible:
            available = {action.id for action in self.snapshot.actions if action.enabled} if self.snapshot else set()
            if {"power", "mara"} <= available:
                lines.append("Power Attack or Mara can interrupt this intent.")
            elif "power" in available:
                lines.append("Power Attack can interrupt this intent.")
            elif "mara" in available:
                lines.append("Mara can interrupt this intent.")
            else:
                lines.append("This intent is interruptible, but no disruption is currently available. Defend to reduce physical damage and recover Focus.")
        else:
            lines.append("This intent cannot be interrupted. Defend reduces physical damage.")
        return "\n".join(lines)

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
        y = self._paragraph(surface, self._health_label(enemy), (x, y), title_width, AMBER if enemy.invulnerable else RED if alive else MUTED, font=body_font)
        y += 1 if compact else 4
        meter = pg.Rect(x, y, title_width, 3 if compact else 5)
        if enemy.invulnerable:
            self._protected_meter(surface, meter)
        else:
            self._health(surface, meter, enemy.hp, enemy.max_hp, actor_id=enemy.id)
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
        interrupt_color = AMBER if self.snapshot and self.snapshot.defensive_objective else TEAL if enemy.interruptible else MUTED
        y = self._paragraph(surface, self._interrupt_label(enemy), (details_x, y), details_width, interrupt_color, font=body_font)
        y += 2 if compact else 6
        self.tooltip_hits.append((pg.Rect(details_x, intent_y, details_width, max(20, y - intent_y)), self._intent_help(enemy)))
        if not wide:
            self._status_line(surface, enemy.statuses, details_x, y, details_width, font=body_font)

    def _draw_attack_effects(self, surface: Any) -> None:
        """Weapon travel lands before numbers, without moving reduced motion."""
        if self._reduced_motion or self.snapshot is None:
            return
        for effect in self._effects:
            feedback = effect.feedback
            if feedback.kind not in {"damage", "evade"} or feedback.actor_id == feedback.target_id or not 0 <= effect.age < 0.36:
                continue
            actor = self.actor_positions.get(feedback.actor_id)
            target = self.actor_rects.get(feedback.target_id)
            if actor is None or target is None:
                continue
            enemy = next((enemy for enemy in self.snapshot.enemies if enemy.id == feedback.actor_id), None)
            kind = "tobin" if feedback.actor_id == "tobin" else self._kind(enemy.archetype + " " + enemy.name) if enemy else "player"
            if kind in {"tobin", "archer"} and effect.age < effect.impact_time:
                start = (actor[0], actor[1] - min(35, round(self._arena_rect.h * 0.35)))
                progress = effect.age / effect.impact_time
                end = (target.centerx, target.centery)
                arrow = (round(start[0] + (end[0] - start[0]) * progress), round(start[1] + (end[1] - start[1]) * progress))
                direction = 1 if end[0] > start[0] else -1
                self.pg.draw.line(surface, BONE, (arrow[0] - direction * 12, arrow[1]), arrow, 1)
                self.pg.draw.lines(surface, AMBER, False, [(arrow[0] - direction * 3, arrow[1] - 3), arrow, (arrow[0] - direction * 3, arrow[1] + 3)], 1)
            elif effect.impact_time <= effect.age < effect.impact_time + 0.14:
                radius = min(18, max(7, target.h // 3))
                center = target.center
                if feedback.kind == "evade":
                    center = (center[0] + 20, center[1])
                color = TEAL if feedback.amount == 0 else BONE
                self.pg.draw.line(surface, color, (center[0] - radius, center[1] + radius), (center[0] + radius, center[1] - radius), 2)
                self.pg.draw.line(surface, AMBER if feedback.amount else TEAL, (center[0] - radius + 3, center[1] + radius), (center[0] + radius + 3, center[1] - radius), 1)

    @staticmethod
    def _feedback_label(feedback: CombatFeedback) -> tuple[str, tuple[int, int, int]]:
        if feedback.kind == "damage":
            return (f"−{feedback.amount}", RED) if feedback.amount else ("BLOCKED", TEAL)
        if feedback.kind == "heal":
            return (f"+{feedback.amount}" if feedback.amount else "REMEDY"), TEAL
        if feedback.kind == "phase":
            return "PHASE " + {2: "II", 3: "III"}.get(feedback.amount, str(feedback.amount)), RED
        return {"defend": "GUARDED", "evade": "EVADED", "interrupt": "INTERRUPTED", "fallen": "FALLEN", "escape": "ESCAPED"}.get(feedback.kind, feedback.kind.upper()), AMBER

    def _draw_feedback(self, surface: Any) -> None:
        # A formation can deliver Bleeding and three attacks in a single turn.
        # Keep two readable rows per target, summarizing older numeric hits
        # rather than piling labels above the canvas or under status badges.
        grouped: dict[str, list[_Effect]] = {}
        for effect in self._effects:
            impact = 0 if self._reduced_motion else effect.impact_time
            if effect.age < impact:
                continue
            actor_id = effect.feedback.target_id if effect.feedback.target_id in self.actor_positions else effect.feedback.actor_id
            if actor_id in self.actor_positions:
                grouped.setdefault(actor_id, []).append(effect)
        compact = self._arena_rect.h < 120
        number_font = self.compact_number_font if compact else self.number_font
        word_font = self.mini_font if compact else self.small_font
        for actor_id, effects in grouped.items():
            entries = [(self._feedback_label(effect.feedback), effect.feedback.kind in {"damage", "heal"}) for effect in effects[-2:]]
            if len(effects) > 2:
                outcome = next((effect for effect in reversed(effects) if effect.feedback.kind in {"interrupt", "fallen", "evade", "defend", "escape", "phase"} and effect.age - (0 if self._reduced_motion else effect.impact_time) < 0.9), None)
                previous = effects[:-1]
                damage = [effect.feedback.amount for effect in previous if effect.feedback.kind == "damage"]
                healing = [effect.feedback.amount for effect in previous if effect.feedback.kind == "heal"]
                if outcome is not None and any(effect.feedback.kind in {"damage", "heal"} for effect in effects):
                    damage = [effect.feedback.amount for effect in effects if effect.feedback.kind == "damage"]
                    healing = [effect.feedback.amount for effect in effects if effect.feedback.kind == "heal"]
                    if healing and damage:
                        numeric = (f"+{sum(healing)} / −{sum(damage)}", TEAL)
                    elif healing:
                        suffix = f" ×{len(healing)}" if len(healing) > 1 else ""
                        numeric = (f"+{sum(healing)}{suffix}" if sum(healing) else "REMEDY", TEAL)
                    elif damage:
                        suffix = f" ×{len(damage)}" if len(damage) > 1 else ""
                        numeric = (f"−{sum(damage)}{suffix}", RED) if sum(damage) else (f"BLOCKED{suffix}", TEAL)
                    entries = [(numeric, False), (self._feedback_label(outcome.feedback), False)]
                elif damage and not healing:
                    suffix = f" ×{len(damage)}" if len(damage) > 1 else ""
                    entries[0] = (((f"−{sum(damage)}{suffix}", RED) if sum(damage) else (f"BLOCKED{suffix}", TEAL)), len(damage) == 1 and sum(damage) > 0)
                elif healing and not damage:
                    suffix = f" ×{len(healing)}" if len(healing) > 1 else ""
                    entries[0] = ((f"+{sum(healing)}{suffix}", TEAL), len(healing) == 1)
            glyphs = [(number_font if numeric else word_font).render(text, True, color) for (text, color), numeric in entries]
            total_height = sum(glyph.get_height() + 6 for glyph in glyphs) + 3 * (len(glyphs) - 1)
            actor_rect = self.actor_rects.get(actor_id)
            ideal = self._arena_rect.y + 4 if compact or actor_rect is None else actor_rect.y - total_height - 9
            top = max(self._arena_rect.y + 3, min(ideal, self._arena_rect.bottom - total_height - 3))
            center_x = self.actor_positions[actor_id][0]
            for glyph, ((text, _), _) in zip(glyphs, entries):
                label = self.pg.Rect(0, top, glyph.get_width() + 12, glyph.get_height() + 6)
                label.centerx = center_x
                label.x = max(self._arena_rect.x + 2, min(label.x, self._arena_rect.right - label.w - 2))
                self.pg.draw.rect(surface, INK, label)
                self.pg.draw.rect(surface, EDGE, label, 1)
                surface.blit(glyph, (label.x + 6, label.y + 3))
                self.feedback_rects.append(label)
                self.feedback_labels.append((actor_id, text, label))
                top = label.bottom + 3

    def _draw_tooltip(self, surface: Any) -> None:
        if self._mouse is None:
            return
        text = next((text for rect, text in reversed(self.tooltip_hits) if rect.collidepoint(self._mouse)), None)
        if not text:
            return
        key = (text, self._rect.w, self._rect.h, id(self.small_font), id(self.mini_font))
        if key not in self._tooltip_layout_cache:
            width = min(320, max(170, self._rect.w - 32))
            maximum = max(1, self._rect.h - 12)
            font = self.small_font

            def layout(selected_font: Any) -> tuple[list[str], int]:
                lines = [line for paragraph in text.splitlines() for line in _wrapped(paragraph, selected_font, width - 20)]
                return lines, len(lines) * selected_font.get_linesize() + 16

            lines, height = layout(font)
            if height > maximum:
                width = max(40, self._rect.w - 16)
                lines, height = layout(font)
            if height > maximum:
                font = self.mini_font
                lines, height = layout(font)
            if height > maximum:
                lower, upper = 0.35, 1.0
                for _ in range(9):
                    scale = round((lower + upper) / 2, 4)
                    fitted_key = (id(self.mini_font), scale)
                    if fitted_key not in self._fitted_fonts:
                        self._fitted_fonts[fitted_key] = _ScaledFont(self.pg, self.mini_font, scale)
                    candidate = self._fitted_fonts[fitted_key]
                    candidate_lines, candidate_height = layout(candidate)
                    if candidate_height <= maximum:
                        lower = scale
                        font, lines, height = candidate, candidate_lines, candidate_height
                    else:
                        upper = scale
            if len(self._tooltip_layout_cache) >= 32:
                self._tooltip_layout_cache.clear()
            self._tooltip_layout_cache[key] = font, lines, width, height
        font, lines, width, height = self._tooltip_layout_cache[key]
        x = max(self._rect.x + 8, min(self._mouse[0] + 12, self._rect.right - width - 8))
        y = max(self._rect.y + 4, min(self._mouse[1] - height - 10, self._rect.bottom - height - 4))
        rect = self.pg.Rect(x, y, width, height)
        self.tooltip_rect = rect.copy()
        self.pg.draw.rect(surface, INK, rect)
        self.pg.draw.rect(surface, AMBER, rect, 1)
        for line in lines:
            self._text(surface, line, (x + 10, y + 8), BONE, font=font)
            y += font.get_linesize()

    def draw(self, surface: Any, rect: Any, now_ms: int = 0) -> Any:
        """Draw the arena and full intent cards inside ``rect`` and return it."""
        pg = self.pg
        rect = pg.Rect(rect)
        self._rect = rect.copy()
        self.enemy_hits.clear()
        self.sprite_hits.clear()
        self.tooltip_hits.clear()
        self.actor_positions.clear()
        self.actor_rects.clear()
        self.party_hits.clear()
        self.condition_hits.clear()
        self.feedback_rects.clear()
        self.feedback_labels.clear()
        self.target_marker_rect = None
        self.tooltip_rect = None
        if self.snapshot is None or rect.w <= 0 or rect.h <= 0:
            return rect
        snapshot = self.snapshot
        previous_clip = surface.get_clip()
        surface.set_clip(rect.clip(previous_clip))
        pg.draw.rect(surface, INK, rect)
        label = {"active": "CHOOSE YOUR MOVE", "victory": "THE ROAD IS YOURS", "defeat": "THE SHADOW PREVAILS", "escaped": "YOU FOUND A WAY OUT"}.get(snapshot.phase, snapshot.phase.upper())
        if snapshot.phase == "victory" and snapshot.defensive_objective:
            label = "YOU HELD THE LINE"
        if snapshot.phase == "active" and self.resolving:
            label = "TURN RESULTS"
        round_label = f"ROUND {snapshot.round_number}" + (f" / {snapshot.max_rounds}" if snapshot.max_rounds else "")
        self._text(surface, round_label, (rect.x + 12, rect.y + 9), AMBER, font=self.banner_font)
        phase_width = self.small_font.size(label)[0]
        phase_left = rect.right - phase_width - 12
        self._text(surface, label, (phase_left, rect.y + 13), TEAL if snapshot.phase == "victory" else MUTED, font=self.small_font)
        condition_left = rect.x + 24 + self.banner_font.size(round_label)[0]
        condition_bottom = self._header_conditions(surface, pg.Rect(condition_left, rect.y + 5, max(40, phase_left - condition_left - 10), 30))
        header_bottom = max(rect.y + 34, condition_bottom + 6)
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
        available_scale = (arena.h - (16 if compact else 25) - 11) / 48
        actor_scale = 2 if available_scale >= 2 and arena.w >= 400 else 1 if available_scale >= 1 else 0.75 if available_scale >= 0.75 else 0.5
        player_x = arena.x + max(65, round(arena.w * 0.19))
        companions = tuple(companion for companion in snapshot.companions if companion.available)[:2]
        party_scale = 0.5 if actor_scale < 1 else 0.75 if actor_scale == 1 else 1.5
        ally_edge = arena.x + max(18, round(20 * party_scale))
        ally_anchors = [(max(ally_edge, player_x - (36 if actor_scale <= 1 else 62) - index * (29 if actor_scale <= 1 else 40)), ground - 4 - index * 3) for index in range(len(companions))]
        enemies = snapshot.enemies
        enemy_left = arena.x + round(arena.w * 0.50)
        enemy_span = max(1, arena.right - 35 - enemy_left)
        enemy_anchors = [(enemy_left + round(enemy_span * ((index + 0.5) / max(1, len(enemies)))), ground) for index in range(len(enemies))]
        # Resolve every destination before drawing the first actor. Otherwise
        # player attacks cannot travel toward enemies rendered later in order.
        self.actor_positions.update({"player": (player_x, ground), **{ally.id: anchor for ally, anchor in zip(companions, ally_anchors)}, **{enemy.id: anchor for enemy, anchor in zip(enemies, enemy_anchors)}})
        self._draw_actor(surface, "player", "player", (player_x, ground), actor_scale, facing_left=False, alive=snapshot.player.hp > 0, now_ms=now_ms)
        player_label = snapshot.player.name
        label_width = min(140, round(arena.w * 0.30))
        while len(player_label) > 1 and self.small_font.size(player_label)[0] > label_width:
            player_label = player_label[:-2].rstrip() + "…"
        if "player" in self.actor_rects and snapshot.phase != "escaped":
            self._text(surface, player_label, (player_x - self.small_font.size(player_label)[0] // 2, ground + 3), BONE, font=self.small_font)
        # Companions stand a step behind the traveler rather than becoming
        # abstract ability names in a menu.
        for index, companion in enumerate(companions):
            ally_x, ally_ground = ally_anchors[index]
            self._draw_actor(surface, companion.id, self._kind(companion.id + companion.name), (ally_x, ally_ground), party_scale, facing_left=False, now_ms=now_ms)
            if companion.id in self.actor_rects and snapshot.phase != "escaped":
                self._text(surface, companion.name, (ally_x - self.party_font.size(companion.name)[0] // 2, ally_ground + 3), TEAL, font=self.party_font)
        for index, enemy in enumerate(enemies):
            enemy_x, _ = enemy_anchors[index]
            self._draw_actor(surface, enemy.id, self._kind(enemy.archetype + " " + enemy.name), (enemy_x, ground), actor_scale, facing_left=True, alive=enemy.hp > 0, targeted=enemy.id == snapshot.target_id, now_ms=now_ms)
            if enemy.hp > 0:
                meter = pg.Rect(enemy_x - 23, ground + 5, 46, 3)
                if enemy.invulnerable:
                    self._protected_meter(surface, meter)
                else:
                    self._health(surface, meter, enemy.hp, enemy.max_hp, actor_id=enemy.id)
                number = str(index + 1)
                number_pos = (enemy_x - 34, ground + 1) if compact else (enemy_x - 3, ground + 10)
                self._text(surface, number, number_pos, AMBER if enemy.id == snapshot.target_id else MUTED, font=self.mini_font if compact else self.small_font)
        self._draw_attack_effects(surface)
        self._draw_feedback(surface)
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
