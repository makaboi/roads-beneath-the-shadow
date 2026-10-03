"""Pixel-art presentation of the complete story engine.

The story runs in a worker and only communicates through queues.  Pygame and
its display, font, and input APIs stay on the calling (main) thread.
"""

from __future__ import annotations

import re
import os
import threading
from weakref import WeakKeyDictionary, ref
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from .lighting import Color
from .narrative import NarrativeDirector
from .combat_view import CombatCommand, CombatTurnSummary
from .controller_input import GamepadInput
from .pixel_battle import BattleView
from .pixel_font import caret_positions, text_clusters, text_viewport
from .pixel_keyboard import NameKeyboard
from .pixel_panels import PanelView
from .pixel_theme import draw_pixel_frame, initial_window_size, load_font, wrap_text
from .pixel_transcript import TranscriptView
from .pixel_world import WorldView
from .player_view import player_snapshot
from .soundscapes import SoundscapePlayer
from .text_input import TextEntry
from .ui import InputClosed, TerminalUI, choice_number


INK = (16, 21, 27)
PANEL = (23, 31, 38)
PARCHMENT = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 156, 151)
MUTED = (159, 161, 150)
RED = (219, 132, 113)
SCENE_CACHE_BYTES = 64 * 1024 * 1024
BATTLE_BACKDROPS = {
    "branch_fight": "tavern-battle",
    "branch_hide": "tavern-battle",
    "branch_search": "tavern-battle",
    "branch_escape": "tavern-battle",
    "branch_question": "tavern-battle",
    "marsh_ambush": "marsh-battle",
    "final_battle": "marsh-battle",
    "part2_pursuit": "dead-road-battle",
    "part2_chain_troll": "sluice-battle",
    "part2_teren": "seal-vault-battle",
    "part2_final_battle": "seal-vault-battle",
    "part2_echo_bridge": "echo-bridge-battle",
}
BATTLE_GROUND_Y = {"echo-bridge-battle": 135.0, "tavern-battle": 170.0, "marsh-battle": 170.0, "dead-road-battle": 170.0, "sluice-battle": 170.0, "seal-vault-battle": 170.0}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
STORY_COMMANDS = (("i", "Inventory"), ("c", "Character"), ("j", "Journal"), ("s", "Save"), ("r", "Road map"), ("m", "Main menu"), ("p", "Pause"), ("h", "Controls"))
UTILITY_COMMANDS = tuple(command for command in STORY_COMMANDS if command[0] in {"i", "c", "j", "s", "r", "p"})


@dataclass(frozen=True)
class UIEvent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InputRequest:
    identifier: int
    kind: str
    label: str
    options: tuple[str, ...] = ()
    allow_back: bool = False
    story: bool = False
    context: dict[str, Any] = field(default_factory=dict)


class PixelUI(TerminalUI):
    """A drop-in UI adapter; no graphical dependency is imported here."""

    supports_checkpoints = True
    supports_graphical_settings = True

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("color", True)
        super().__init__(**kwargs)
        self.events: Queue[UIEvent] = Queue()
        self.responses: Queue[tuple[int, Any]] = Queue()
        self.closed = threading.Event()
        self.state_provider: Callable[[], Any] = lambda: None
        self._request_number = 0
        self.music_volume = 0.25
        self.sfx_volume = 0.6
        self.text_size = "standard"
        self.story_decision_token: str | None = None
        self._creating_traveler = False
        self._creation_source: Any = None
        self._state_reference: Any = None
        self._presentation_number = 0
        self._transcript_state_reference: Any = None

    @property
    def width(self) -> int:
        return 78

    @staticmethod
    def _supports_color() -> bool:
        return True

    def style(self, text: str, *codes: str) -> str:
        return ANSI.sub("", text)

    def _post(self, kind: str, **data: Any) -> None:
        if self.closed.is_set():
            raise InputClosed
        state = self.state_provider()
        if state is not None and (self._transcript_state_reference is None or self._transcript_state_reference() is not state):
            # Post the boundary before the first output from an accepted new
            # traveler or loaded checkpoint. Continuing and canceling creation
            # keep the same state object and preserve the current archive.
            self._transcript_state_reference = ref(state)
            self.events.put(UIEvent("journey"))
        self.events.put(UIEvent(kind, data))

    def _request(self, kind: str, label: str, options: Sequence[str] = (), *, allow_back: bool = False, story: bool = False, context: dict[str, Any] | None = None) -> Any:
        if self.closed.is_set():
            raise InputClosed
        self._request_number += 1
        if kind == "text" and label.strip() == "Traveler's name:":
            source = self.state_provider()
            self._creation_source = ref(source) if source is not None else None
            self._creating_traveler = True
        elif story or label == "MAIN MENU":
            self._creating_traveler = False
            self._creation_source = None
        hud = self._hud_snapshot()
        request_context = dict(context or {})
        if story:
            request_context.setdefault("decision_id", self.story_decision_token)
        if hud:
            request_context.setdefault("companions", hud["companions"])
            for key in ("scene", "chapter", "journey_id", "origin", "presentation_id"):
                request_context.setdefault(key, hud.get(key))
        request = InputRequest(self._request_number, kind, label, tuple(str(option) for option in options), allow_back, story, request_context)
        self._post("request", request=request, hud=hud)
        while not self.closed.is_set():
            try:
                identifier, answer = self.responses.get(timeout=0.1)
            except Empty:
                continue
            if identifier == request.identifier:
                return answer
        raise InputClosed

    def _hud_snapshot(self) -> dict[str, Any] | None:
        state = self.state_provider()
        if self._creating_traveler:
            source = self._creation_source() if self._creation_source is not None else None
            if state is source:
                return None
            self._creating_traveler = False
            self._creation_source = None
        snapshot = player_snapshot(state)
        if snapshot is not None:
            if self._state_reference is None or self._state_reference() is not state:
                self._state_reference = ref(state)
                self._presentation_number += 1
            snapshot["presentation_id"] = self._presentation_number
        return snapshot

    def close(self) -> None:
        """Release a waiting story worker when the player closes the window."""
        self.closed.set()
        self.responses.put((-1, None))

    def submit(self, request: InputRequest, answer: Any) -> None:
        self.responses.put((request.identifier, answer))

    def clear(self) -> None:
        self._post("clear")

    def write(self, text: str = "", *, color: str | None = None, bold: bool = False) -> None:
        self._post("text", text=ANSI.sub("", str(text)), color=color, bold=bold)

    def rule(self, char: str = "=") -> None:
        self._post("rule")

    def title(self, text: str) -> None:
        self._post("title", text=text.strip())

    def narrate(self, text: str, *, color: str | None = None) -> None:
        self._post("text", text=text.strip(), color=color, bold=False, narration=True)

    def art(self, text: str, color: str = Color.SILVER, *, alt_text: str | None = None) -> None:
        self._post("art", text=text, color=color, alt_text=alt_text, reduced_motion=self.reduced_motion)
        if self.screen_reader and alt_text:
            self.write(f"[Scene: {alt_text}]")

    def animate(self, frames: Sequence[str], color: str = Color.SILVER, *, frame_delay: float = 0.14, repeat: int = 1, alt_text: str | None = None, frame_offsets: Sequence[int] | None = None) -> None:
        if frames:
            self.art(frames[-1], color, alt_text=alt_text)

    def choose(self, title: str, options: Sequence[str], *, allow_back: bool = False) -> int | None:
        if not options:
            raise ValueError("choose requires at least one option")
        return self._request("choice", title, options, allow_back=allow_back)

    def choose_settings(self, title: str, options: Sequence[str], *, allow_back: bool = False) -> int | None:
        """Keep the adjusted control in view while this settings visit lasts."""
        if not options:
            raise ValueError("choose_settings requires at least one option")
        return self._request("choice", title, options, allow_back=allow_back,
                             context={"navigation_group": "settings"})

    def choose_story(self, heading: str, options: Sequence[str]) -> int | str | None:
        if not options:
            raise ValueError("choose_story requires at least one option")
        return self._request("choice", heading, options, story=True)

    def combat_snapshot(self, snapshot: Any) -> None:
        self._post("combat_snapshot", snapshot=snapshot)

    def combat_begin(self) -> None:
        self._post("combat_begin")

    def combat_feedback(self, feedback: Any) -> None:
        self._post("combat_feedback", feedback=feedback)

    def choose_combat(self, options: Sequence[str]) -> Any:
        return self._request("combat", "Choose your action", options)

    def show_panel(self, kind: str, data: dict[str, Any]) -> Any:
        return self._request("panel", kind.title(), context={"kind": kind, "data": data})

    def choose_background(self, data: dict[str, Any]) -> Any:
        return self._request("panel", "Choose your background", context={"kind": "background", "data": data})

    def toast(self, text: str, *, kind: str = "notice") -> None:
        self._post("toast", text=text, toast_kind=kind)

    def begin_creation(self) -> None:
        self._post("creation_begin")

    def cancel_creation(self) -> None:
        self._post("creation_cancel")

    def prompt(self, label: str = "> ") -> str:
        limit = 24 if label.strip() == "Traveler's name:" else 64
        return str(self._request("text", label, context={"max_length": limit})).strip()

    def choose_name(self, label: str = "Traveler's name: ") -> str | None:
        answer = self._request("text", label, allow_back=True, context={"max_length": 24})
        return None if answer is None else str(answer).strip()

    def pause(self, message: str = "Press Return to continue...") -> None:
        self._request("pause", message)

    def sound(self, cue: str = "notice") -> None:
        if self.sound_enabled:
            self._post("sound", cue=cue)


def wrap_pixels(text: str, font: Any, width: int) -> list[str]:
    """Wrap to measured pixels, including unusually long names or words."""
    return wrap_text(text, font, width)


class PixelWindow:
    """Main-thread renderer, exposed separately for real SDL input tests."""

    def __init__(self, ui: PixelUI, *, size: tuple[int, int] | None = None) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError as error:
            raise RuntimeError("Pixel mode needs pygame-ce. Install it with: python3 -m pip install . (or launch with --terminal)") from error
        self.pg = pygame
        self.ui = ui
        # Audio is initialized lazily by the sound player, after opt-in.
        pygame.display.init()
        pygame.font.init()
        if size is None:
            desktops = pygame.display.get_desktop_sizes()
            size = initial_window_size(desktops[0] if desktops else (0, 0))
        pygame.display.set_caption("Roads Beneath the Shadow — Pixel Edition")
        try:
            self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        except pygame.error as error:
            pygame.quit()
            raise RuntimeError("A graphical display could not be opened. Launch with --terminal for terminal play.") from error
        self.clock = pygame.time.Clock()
        self.font = load_font(pygame, 17)
        self.small_font = load_font(pygame, 13)
        self.title_font = load_font(pygame, 24, bold=True)
        self._font_key = (17, 13, 24)
        self.line_height = self.font.get_linesize() + 3
        self.history: list[tuple[str, Any, bool]] = []
        self.request: InputRequest | None = None
        self.selected = 0
        self.choice_scroll = 0
        self._menu_focused = False
        self.history_scroll = 0
        self._entry_editor = TextEntry()
        self._entry_view_start = 0
        self._entry_view_end = 0
        self._entry_field = pygame.Rect(0, 0, 0, 0)
        self._entry_text_x = 0
        self.entry_composition = ""
        self.heading = "THE ROAD AWAITS"
        self.scene_caption = "An eight-pointed star above a winding road."
        self.hud: dict[str, Any] | None = None
        self.scene = None
        self.scene_key = "title"
        self.scene_cache: dict[str, Any] = {}
        self._scaled_scenes: dict[tuple[str, tuple[int, int]], Any] = {}
        self.choice_hits: list[tuple[Any, Any]] = []
        self.utility_hits: list[tuple[Any, str]] = []
        self.art_rect = pygame.Rect(0, 0, 0, 0)
        self.history_rect = pygame.Rect(0, 0, 0, 0)
        self.menu_rect = pygame.Rect(0, 0, 0, 0)
        self.fullscreen = False
        self.minimized = False
        self._minimized_at: int | None = None
        self.window_size = size
        self._windowed_position: tuple[int, int] | None = None
        self._restoring_window_size: tuple[int, int] | None = None
        self.finished = False
        self.error: str | None = None
        self._sound_cache: dict[str, Any] = {}
        self._text_layout: list[tuple[str, Any, bool]] = []
        self._history_layout_key: tuple[Any, ...] | None = None
        self._reveals: dict[int, float] = {}
        self._last_tick = pygame.time.get_ticks()
        self.narrative = NarrativeDirector()
        self.world = WorldView(pygame)
        self.battle = BattleView(pygame)
        self.panels = PanelView(pygame)
        self.name_keyboard = NameKeyboard(pygame)
        self._name_keyboard_hit = pygame.Rect(0, 0, 0, 0)
        self.gamepad = GamepadInput(pygame)
        self.archive = TranscriptView(pygame)
        self.soundscape = SoundscapePlayer(pygame)
        self.transcript_open = False
        self._saved_narrative: NarrativeDirector | None = None
        self._saved_journey: str | None = None
        self._saved_decision: tuple[Any, ...] | None = None
        self._saved_navigation: tuple[int, int, bool] | None = None
        self._settings_navigation: tuple[int, int, bool] | None = None
        self._choice_view_key: tuple[Any, ...] | None = None
        self._combat_help_layout_key: tuple[Any, ...] | None = None
        self._combat_help_lines: tuple[list[str], ...] = ()
        self._creation_archive_start: int | None = None
        self._read_boundaries: Any = WeakKeyDictionary()
        self._page_token: Any = None
        self._page_reveal = 0.0
        self._layout_size: tuple[int, int] | None = None
        self._frame_tick = pygame.time.get_ticks()
        self._toasts: list[tuple[str, float]] = []
        self._toasts_deferred = False
        self._combat_active = False
        self._battle_transition_hold = False
        self._local_help = False
        self._battle_log: list[tuple[str, Any, bool]] = []
        self._turn_summary = CombatTurnSummary()
        self._observation_session: tuple[Any, Any] | None = None
        self._observed_details: set[tuple[str | None, str, str]] = set()
        self._load_scene("", "An eight-pointed star above a winding road.")

    @property
    def entry(self) -> str:
        return self._entry_editor.text

    @entry.setter
    def entry(self, text: str) -> None:
        self._entry_editor.set_text(text)

    @property
    def entry_selected(self) -> bool:
        return self._entry_editor.has_selection

    @entry_selected.setter
    def entry_selected(self, selected: bool) -> None:
        self._entry_editor.select_all() if selected else self._entry_editor.clear_selection()

    def _load_scene(self, text: str, alt_text: str | None) -> None:
        try:
            from .pixel_art import resolve_scene
            path = resolve_scene(text, alt_text)
            if path:
                self.scene_key = Path(path).stem
                key = str(path)
                if key not in self.scene_cache:
                    self.scene_cache[key] = self.pg.image.load(key).convert()
                self.scene = self.scene_cache[key]
        except (ImportError, OSError, ValueError, self.pg.error):
            # Missing artwork never removes a story choice or prevents play.
            pass

    def _battle_backdrop(self) -> Any:
        """Battles keep their location while prose retains its subject art."""
        backdrop = BATTLE_BACKDROPS.get((self.hud or {}).get("scene"))
        if backdrop:
            try:
                from .pixel_art import ASSET_DIR
                key = str(ASSET_DIR / f"{backdrop}.png")
                if key not in self.scene_cache:
                    self.scene_cache[key] = self.pg.image.load(key).convert()
                return self.scene_cache[key]
            except (ImportError, OSError, ValueError, self.pg.error):
                pass
        return self.scene

    def drain(self) -> None:
        if self._local_help:
            return
        # The engine can already be on its next page while the final impact
        # is still travelling. Keep that page queued until the result lands.
        if self._battle_transition_hold:
            if self.battle.busy:
                return
            self._battle_transition_hold = False
        while True:
            try:
                event = self.ui.events.get_nowait()
            except Empty:
                break
            data = event.data
            if event.kind == "journey":
                self._reset_journey_presentation()
            elif event.kind == "creation_begin":
                self._creation_archive_start = len(self.history)
            elif event.kind == "creation_cancel":
                if self._creation_archive_start is not None:
                    del self.history[self._creation_archive_start:]
                    self._reveals = {index: value for index, value in self._reveals.items() if index < self._creation_archive_start}
                    self._text_layout.clear()
                    self._history_layout_key = None
                    self.archive.set_entries(self.history)
                self._creation_archive_start = None
            if event.kind in {"clear", "title", "art", "text"}:
                self.narrative.feed(event)
            if event.kind == "clear":
                if self.history and self.history[-1][0]:
                    self.history.append(("", None, False))
                self.heading = "THE ROAD AWAITS"
                self.history_scroll = 0
            elif event.kind == "text":
                self.history.append((data["text"], data.get("color"), data.get("bold", False)))
                self.history_scroll = 0
            elif event.kind == "title":
                self.heading = data["text"]
                self.history.append((data["text"], Color.YELLOW, True))
                self.history_scroll = 0
            elif event.kind == "art":
                if self.request is None and self.ui.fast:
                    self.scene_caption = data.get("alt_text") or "The road continues beneath the shadow."
                    self._load_scene(data["text"], data.get("alt_text"))
            elif event.kind == "request":
                self.request = data["request"]
                previous_hud = self.hud
                self.hud = data.get("hud")
                self._notice_progress(previous_hud, self.hud)
                self.selected = 0
                self.choice_scroll = 0
                self._menu_focused = False
                if self.request.context.get("navigation_group") == "settings":
                    if self._settings_navigation is not None:
                        self.selected, self.choice_scroll, self._menu_focused = self._settings_navigation
                        self.selected = min(self.selected, max(0, len(self.request.options) - 1))
                else:
                    self._settings_navigation = None
                self._entry_editor = TextEntry(max_length=self.request.context.get("max_length", 64))
                self._entry_view_start = 0
                self._entry_view_end = 0
                self.entry_composition = ""
                self.pg.key.start_text_input() if self.request.kind == "text" else self.pg.key.stop_text_input()
                if self.request.kind == "panel":
                    self.panels.open(self.request.context["kind"], self.request.context["data"])
                    self.world.set_request(None, preserve_inspection=self._saved_narrative is not None)
                else:
                    self.panels.close()
                    restored_narrative = False
                    if self.request.story and self._saved_narrative is not None:
                        if self._same_decision(self._decision_key(self.request, self.hud), self._saved_decision):
                            self.narrative = self._saved_narrative
                            self.narrative.discard_pending()
                            restored_narrative = True
                            if self._saved_navigation is not None:
                                self.selected, self.choice_scroll, self._menu_focused = self._saved_navigation
                                self.selected = min(self.selected, max(0, len(self.request.options) - 1))
                        self._saved_narrative = None
                        self._saved_decision = None
                        self._saved_navigation = None
                    cinematic = False if self.ui.fast else None
                    if self.request.kind == "combat" and not self._combat_active and not self.ui.fast:
                        cinematic = True
                    self._combat_active = self.request.kind == "combat" or (self.battle.snapshot is not None and self.battle.snapshot.phase == "active" and not self.request.story and self.hud is not None)
                    if self.request.label == "MAIN MENU" or self.request.story:
                        self._combat_active = False
                    _, rows, text_width = self._reading_dimensions()
                    if restored_narrative:
                        self.narrative.repaginate(wrap=lambda text: wrap_pixels(text, self.font, text_width), rows=rows)
                        if self.narrative.pages:
                            self.narrative.index = len(self.narrative.pages) - 1
                    else:
                        self._read_boundaries.pop(self.narrative, None)
                        self.narrative.prepare(self.request, wrap=lambda text: wrap_pixels(text, self.font, text_width), rows=rows, cinematic=cinematic, suppress_headers={"COMBAT"} if self.request.kind == "combat" else ())
                    self._sync_page()
                    if restored_narrative:
                        # Utility commands only become available after the
                        # current story page has been read. Preserve that fact.
                        self._finish_narration()
                    self._sync_world()
            elif event.kind == "combat_begin":
                self.battle.set_snapshot(None)
                self._battle_log = []
                self._turn_summary = CombatTurnSummary()
                self._combat_active = False
                self._battle_transition_hold = False
            elif event.kind == "combat_snapshot":
                snapshot = data["snapshot"]
                if snapshot.phase == "active" and snapshot.round_number == 1 and self.battle.snapshot is not None and self.battle.snapshot.phase != "active":
                    self._battle_log = []
                self.battle.set_snapshot(data["snapshot"])
                if snapshot.phase != "active" and self.battle.busy:
                    self._battle_transition_hold = True
                    self._combat_active = True
                    break
            elif event.kind == "combat_feedback":
                feedback = data["feedback"]
                self._turn_summary = self._turn_summary.append(feedback)
                if feedback.kind == "notice":
                    self._toast(feedback.text)
                if feedback.text:
                    text = feedback.text
                    if feedback.kind == "damage":
                        text += f" · −{feedback.amount} Health"
                    elif feedback.kind == "heal":
                        text += f" · +{feedback.amount} Health"
                    elif feedback.kind == "defend" and feedback.amount:
                        text += f" · +{feedback.amount} Focus"
                    self._battle_log.append((text, Color.GREEN if feedback.kind in {"heal", "defend", "evade"} else None, False))
                    self._battle_log = self._battle_log[-24:]
                self.battle.queue_feedback(data["feedback"])
            elif event.kind == "toast":
                self._toast(data["text"])
            elif event.kind == "sound":
                self._play_sound(data["cue"])
            elif event.kind == "finished":
                self.finished = True
                self.request = None
                self.error = data.get("error")
                if self.error:
                    self.history.append((self.error, Color.RED, True))
                    self.history_scroll = 0
                    self.narrative = NarrativeDirector()
                    self._combat_active = False
                    self.world.set_request(None)
                    self.panels.close()
                    self.archive.close()
                    self.transcript_open = False
                else:
                    self.ui.close()

    def _reset_journey_presentation(self) -> None:
        self.history.clear()
        self.history_scroll = 0
        self._text_layout.clear()
        self._history_layout_key = None
        self._reveals.clear()
        self.archive.reset()
        self.name_keyboard.close()
        self.gamepad.reset()
        self.transcript_open = False
        self.narrative = NarrativeDirector()
        self._saved_narrative = None
        self._saved_decision = None
        self._saved_navigation = None
        self._settings_navigation = None
        self._choice_view_key = None
        self._creation_archive_start = None
        self._read_boundaries.clear()
        self._page_token = None
        self._page_reveal = 0.0
        self.world.set_request(None)
        self.world.reset_observations()
        self.battle.set_snapshot(None)
        self._battle_log.clear()
        self._turn_summary = CombatTurnSummary()
        self._combat_active = False
        self._battle_transition_hold = False
        self._observed_details.clear()
        self._observation_session = None
        self._toasts.clear()
        self._toasts_deferred = False
        self.hud = None

    @property
    def reading(self) -> bool:
        return self.narrative.cinematic and (self.narrative.has_next or not self._page_finished)

    @property
    def _page_finished(self) -> bool:
        page = self.narrative.current
        return page is None or self._page_reveal >= len(page.text)

    def _reading_dimensions(self) -> tuple[int, int, int]:
        width, height = self.screen.get_size()
        margin = 22 if width >= 1000 else 15
        left_width = int((width - margin * 2 - 18) * 0.60)
        available = height - 132
        art_height = min(max(190, int(available * 0.65)), available - 130)
        return art_height, max(1, (available - art_height - 18 - 49) // self.line_height), left_width - 40

    def _sync_page(self) -> None:
        page = self.narrative.current
        token = (id(self.narrative), page.start, page.number, page.text) if page else None
        if token != self._page_token:
            self._page_token = token
            self._page_reveal = 0.0 if page and self.narrative.cinematic and self.ui.narration_delay and not self.ui.reduced_motion else float(len(page.text) if page else 0)
            if page:
                boundary = self._read_boundaries.get(self.narrative, {}).get(page.beat_index)
                if boundary is not None:
                    self._page_reveal = max(self._page_reveal, self._visible_to_source(page.text, boundary - self._page_source_offset(page)))
        if page:
            self.heading = page.heading
            self.scene_caption = page.scene_caption or "The road continues beneath the shadow."
            self._load_scene(page.scene_text, page.scene_caption)

    @staticmethod
    def _decision_key(request: InputRequest, hud: dict[str, Any] | None) -> tuple[Any, ...]:
        return ((hud or {}).get("journey_id"), request.context.get("scene", (hud or {}).get("scene")), request.label,
                request.context.get("presentation_id"), request.options, request.context.get("decision_id"))

    @staticmethod
    def _same_decision(current: tuple[Any, ...], saved: tuple[Any, ...] | None) -> bool:
        if saved is None or current[:4] != saved[:4]:
            return False
        return current[4] == saved[4] or (current[5] is not None and current[5] == saved[5])

    def _page_source_offset(self, page: Any) -> int:
        paragraphs = self.narrative.beats[page.beat_index].paragraphs
        return sum(len(" ".join(paragraph.text.split())) + 1 for paragraph in paragraphs[:page.start[1]]) + page.start[2]

    @staticmethod
    def _visible_to_source(text: str, count: int) -> float:
        if count <= 0:
            return 0.0
        if count >= len(" ".join(text.split())):
            return float(len(text))
        visible = 0
        for match in re.finditer(r"\S+", text):
            prefix = " ".join(text[:match.start()].split())
            if len(prefix) + bool(prefix) + len(match.group()) <= count:
                visible = match.end()
            else:
                visible = match.start() + max(0, count - len(prefix) - bool(prefix))
                break
        return float(visible)

    def _remember_page(self) -> None:
        page = self.narrative.current
        if page is None or not self._page_finished:
            return
        read = self._read_boundaries.setdefault(self.narrative, {})
        boundary = self._page_source_offset(page) + len(" ".join(page.text.split()))
        read[page.beat_index] = max(read.get(page.beat_index, 0), boundary)

    def _reflow_narrative(self, *, rows: int, width: int) -> None:
        """Keep already-revealed source text visible when a page rewraps."""
        previous = self.narrative.current
        revealed = self._page_reveal
        finished = previous is not None and self.narrative.cinematic and not self.reading
        self._remember_page()
        boundary = None
        if previous is not None:
            boundary = self._page_source_offset(previous) + len(" ".join(previous.text[:int(revealed)].split()))
        self.narrative.repaginate(wrap=lambda text: wrap_pixels(text, self.font, width), rows=rows)
        if finished and self.narrative.pages:
            self.narrative.index = len(self.narrative.pages) - 1
        self._sync_page()
        if finished:
            self._finish_narration()
            return
        current = self.narrative.current
        if boundary is not None and current is not None and current.beat_index == previous.beat_index:
            self._page_reveal = self._visible_to_source(current.text, boundary - self._page_source_offset(current))

    def _sync_world(self) -> None:
        was_active = self.world.active
        request = self.request if not self.reading and not self.panels.active and not self.transcript_open else None
        suspended = self._saved_narrative is not None or self.panels.active or self.transcript_open or self.reading
        self.world.set_request(request, preserve_inspection=suspended)
        if self.world.active and not was_active:
            self.gamepad.reset()

    def _record_world_inspection(self) -> None:
        if not self.world.inspection_open:
            return
        hud = self.hud or {}
        session = (hud.get("journey_id"), hud.get("presentation_id"))
        if session != self._observation_session:
            self._observed_details.clear()
            self._observation_session = session
        detail = (self.world.map_key, self.world.inspection_title, self.world.inspection_text)
        if detail not in self._observed_details:
            self.history.extend((("Look: " + detail[1], Color.YELLOW, True), (detail[2], None, False)))
            self._observed_details.add(detail)
            self.history_scroll = 0

    def _set_transcript(self, opened: bool, *, scroll: int | None = None) -> None:
        self._finish_narration()
        self.entry_composition = ""
        self.gamepad.reset()
        self.transcript_open = opened
        if opened:
            self.archive.open(self.history, scroll=scroll)
        else:
            self.archive.close()
            if self.request and self.request.kind == "text":
                self.pg.key.start_text_input()
        self.history_scroll = self.archive.scroll if opened else 0
        self._sync_world()

    def _continue_reading(self) -> None:
        self._remember_page()
        if not self._page_finished:
            self._finish_narration()
        elif self.narrative.advance():
            self._sync_page()
        else:
            self.answer("")
        self._sync_world()

    def _toast(self, text: str) -> None:
        if text and (not self._toasts or self._toasts[-1][0] != text):
            self._toasts.append((text, self.pg.time.get_ticks() / 1000 + 4.0))
            self._toasts = self._toasts[-3:]

    def _notice_progress(self, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
        if not old or not new or old.get("journey_id") != new.get("journey_id"):
            return
        old_items = {item["id"]: item["count"] for item in old.get("items", [])}
        for item in new.get("items", []):
            if item["count"] > old_items.get(item["id"], 0):
                self._toast("Acquired " + item["name"])
        for quest in new.get("completedquests", []):
            if quest not in old.get("completedquests", []):
                self._toast("Completed: " + str(quest))
        for quest in new.get("activequests", []):
            if quest not in old.get("activequests", []):
                self._toast("New quest: " + str(quest))

    def _play_sound(self, cue: str) -> None:
        self.soundscape.play_cue(cue, enabled=self.ui.sound_enabled, volume=self.ui.sfx_volume)

    def answer(self, answer: Any) -> None:
        if self.request is not None:
            if self.request.kind == "text" and self.entry_composition and answer is not None:
                return
            if self.reading:
                return
            self._finish_narration()
            if self.request.context.get("navigation_group") == "settings":
                if type(answer) is int and 1 <= answer < len(self.request.options):
                    self._settings_navigation = (answer - 1, self.choice_scroll, True)
                else:
                    self._settings_navigation = None
            utility = self.request.story and isinstance(answer, str) and answer in dict(STORY_COMMANDS)
            if utility:
                self._saved_narrative = self.narrative
                self._saved_journey = self.hud.get("journey_id") if self.hud else None
                self._saved_decision = self._decision_key(self.request, self.hud)
                self._saved_navigation = (self.selected, self.choice_scroll, self._menu_focused)
                self.narrative = NarrativeDirector()
                self.narrative.scene_text = self._saved_narrative.scene_text
                self.narrative.scene_caption = self._saved_narrative.scene_caption
            if self.request.story and isinstance(answer, int) and 1 <= answer <= len(self.request.options):
                self.history.append(("> " + self.request.options[answer - 1], Color.CYAN, False))
                self.history_scroll = 0
            self.ui.submit(self.request, answer)
            self.request = None
            self.name_keyboard.close()
            self.gamepad.reset()
            self.panels.close()
            self.world.set_request(None, preserve_inspection=utility or self._saved_narrative is not None)
            self.choice_hits = []
            self.utility_hits = []
            self.pg.key.stop_text_input()

    def _open_name_keyboard(self) -> None:
        if (self.request is not None and self.request.kind == "text"
                and not self.reading and not self.panels.active and not self.transcript_open):
            if self.entry_composition:
                self._toast("Finish composing the name before opening the keyboard.")
                return
            self.name_keyboard.open()
            self.gamepad.reset()

    def _apply_keyboard_edit(self, edit: Any) -> None:
        if edit is None or self.request is None or self.request.kind != "text":
            return
        if edit.kind == "close":
            self.gamepad.reset()
            return
        # An input-method composition still belongs to the physical editor.
        if self.entry_composition:
            return
        if edit.kind == "insert":
            self._entry_editor.insert(edit.text)
        elif edit.kind == "backspace":
            self._entry_editor.backspace()
        elif edit.kind == "confirm" and self.entry.strip():
            self.answer(self.entry)

    def _dispatch_pad(self, action: Any) -> None:
        """Use the existing request and modal rules for mapped pad actions."""
        pg = self.pg
        command = action.id
        if self.name_keyboard.active:
            if command in {"up", "down", "left", "right", "confirm", "back"}:
                self._apply_keyboard_edit(self.name_keyboard.command(command))
            return
        if command == "inventory" and self.request is not None and self.request.kind == "text":
            self._open_name_keyboard()
            return
        if command in {"up", "down", "left", "right"}:
            # Horizontal menu navigation must never inherit the keyboard's
            # Right-to-confirm shortcut: held directions may repeat.
            if command in {"left", "right"} and not self.panels.active and not self.transcript_open:
                return
            key = {"up": pg.K_UP, "down": pg.K_DOWN, "left": pg.K_LEFT, "right": pg.K_RIGHT}[command]
        elif command == "confirm":
            key = pg.K_RETURN
        elif command == "back":
            key = pg.K_BACKSPACE if self.reading and not self.panels.active and not self.transcript_open else pg.K_ESCAPE
        elif command == "archive":
            key = pg.K_TAB
        elif command == "pause":
            # Pause also closes an existing modal through its normal Back.
            key = pg.K_ESCAPE
        elif command in {"previous_target", "next_target"}:
            if self.transcript_open or self.panels.active:
                key = pg.K_PAGEUP if command == "previous_target" else pg.K_PAGEDOWN
            elif self._combat_active and self.request is not None and self.request.kind == "combat":
                key = pg.K_LEFTBRACKET if command == "previous_target" else pg.K_RIGHTBRACKET
            else:
                return
        elif command == "inventory" and self._combat_active and self.request is not None and self.request.kind == "combat":
            actions = self.battle.snapshot.actions if self.battle.snapshot else ()
            index = next((i for i, item in enumerate(actions, 1) if item.id == "inspect"), None)
            if index is not None:
                self._choose(index)
            return
        elif command in {"inventory", "journal", "map", "character"}:
            if self.request is None or not self.request.story or self.panels.active or self.transcript_open or self.reading:
                return
            character = {"inventory": "i", "journal": "j", "map": "r", "character": "c"}[command]
            self.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.key.key_code(character), unicode=character, mod=0))
            return
        else:
            return
        self.handle_event(pg.event.Event(pg.KEYDOWN, key=key, unicode="", mod=0))

    def _toggle_fullscreen(self) -> None:
        pg = self.pg
        try:
            if self.fullscreen:
                # set_mode resizes before leaving fullscreen in pygame-ce
                # 2.5.8. SDL can ignore that resize, leaving a desktop-sized
                # window on X11. Leave fullscreen before requesting the size.
                # The headless dummy driver has no native fullscreen toggle.
                if pg.display.get_driver() != "dummy":
                    pg.display.toggle_fullscreen()
                    if pg.display.is_fullscreen():
                        raise pg.error("The display did not leave fullscreen")
                self.screen = pg.display.set_mode(self.window_size, pg.RESIZABLE)
                self._restoring_window_size = self.window_size
                if self._windowed_position is not None:
                    try:
                        pg.display.set_window_position(self._windowed_position)
                    except pg.error:
                        # Some drivers let the compositor choose placement.
                        # Position support must not block restoring the size.
                        pass
            else:
                self.window_size = self.screen.get_size()
                try:
                    self._windowed_position = pg.display.get_window_position()
                except pg.error:
                    self._windowed_position = None
                self.screen = pg.display.set_mode((0, 0), pg.FULLSCREEN)
                self._restoring_window_size = None
            self.fullscreen = pg.display.is_fullscreen()
        except pg.error:
            # An unsupported native toggle must not terminate a pending story
            # request. Keep rendering the surface and mode SDL actually owns.
            self.screen = pg.display.get_surface() or self.screen
            self.fullscreen = pg.display.is_fullscreen()
            self._toast("This display could not change fullscreen mode.")

    def handle_event(self, event: Any) -> None:
        pg = self.pg
        for action in self.gamepad.handle_event(event):
            if not self.minimized:
                self._dispatch_pad(action)
        if event.type == pg.QUIT:
            self.ui.close()
            return
        if event.type == pg.WINDOWMINIMIZED:
            if not self.minimized:
                self._minimized_at = pg.time.get_ticks()
            self.minimized = True
            self.entry_composition = ""
            self.world.stop_moving()
            self.gamepad.reset()
            return
        if event.type in (pg.WINDOWRESTORED, pg.WINDOWMAXIMIZED):
            now = pg.time.get_ticks()
            if self.minimized and self._minimized_at is not None:
                pause_start = self._minimized_at / 1000
                hidden_seconds = max(0, now - self._minimized_at) / 1000
                self._toasts[:] = [
                    (text, min(now / 1000 + 4.0, expires + hidden_seconds))
                    for text, expires in self._toasts if expires > pause_start
                ]
            self.minimized = False
            self._minimized_at = None
            self.gamepad.reset()
            # Hidden time must not finish a page reveal or skip an impact.
            self._frame_tick = self._last_tick = now
            return
        if event.type == pg.VIDEORESIZE and not self.fullscreen:
            if self._restoring_window_size is not None:
                actual_size = pg.display.get_window_size()
                if (event.w, event.h) != actual_size:
                    # Already-fetched fullscreen resize events may arrive
                    # after F11. They cannot replace the restored dimensions.
                    return
                if actual_size == self._restoring_window_size:
                    self.screen = pg.display.get_surface()
                    return
                # A real later drag changes SDL's size before its event arrives.
                self._restoring_window_size = None
            # Pygame 2 has already resized the live display surface. Asking
            # SDL to resize it again for every queued notification creates
            # unnecessary native transitions and can replay an obsolete size.
            self.screen = pg.display.get_surface() or self.screen
            native_size = self.screen.get_size()
            self.window_size = (max(760, native_size[0]), max(560, native_size[1]))
            if native_size != self.window_size:
                self.screen = pg.display.set_mode(self.window_size, pg.RESIZABLE)
            return
        if event.type == getattr(pg, "WINDOWFOCUSLOST", -1):
            self.entry_composition = ""
            self.world.stop_moving()
            self.battle.handle_event(event)
            if self.transcript_open:
                self.archive.handle_event(event)
            elif self.panels.active:
                self.panels.handle_event(event)
            return
        if self.minimized:
            return
        if event.type == pg.KEYDOWN and event.key == pg.K_F11:
            self._toggle_fullscreen()
            return
        if event.type == pg.KEYDOWN and event.key == pg.K_F1 and not self.panels.active and not self.transcript_open:
            from .controls import controls_snapshot

            self._local_help = True
            self.name_keyboard.close()
            self.gamepad.reset()
            self.entry_composition = ""
            self.panels.open("information", controls_snapshot())
            self.world.stop_moving()
            self._sync_world()
            pg.key.stop_text_input()
            return
        if self.name_keyboard.active:
            handled, edit = self.name_keyboard.handle_event(event)
            self._apply_keyboard_edit(edit)
            if handled:
                return
            if event.type == pg.KEYDOWN:
                command = {pg.K_UP: "up", pg.K_DOWN: "down", pg.K_LEFT: "left", pg.K_RIGHT: "right",
                           pg.K_RETURN: "confirm", pg.K_KP_ENTER: "confirm", pg.K_ESCAPE: "back"}.get(event.key)
                if command:
                    self._apply_keyboard_edit(self.name_keyboard.command(command))
                    return
                if event.key not in (pg.K_BACKSPACE, pg.K_DELETE, pg.K_HOME, pg.K_END, pg.K_a):
                    return
        if self.transcript_open:
            if event.type == pg.KEYDOWN and event.key == pg.K_TAB:
                self._set_transcript(False)
            elif self.archive.handle_event(event):
                self._set_transcript(False)
            if self.transcript_open:
                self.history_scroll = self.archive.scroll
            return
        if self.panels.active:
            handled, action = self.panels.handle_event(event)
            if action is not None:
                if self._local_help:
                    self._local_help = False
                    self.panels.close()
                    self.gamepad.reset()
                    self._sync_world()
                    if self.request and self.request.kind == "text":
                        pg.key.start_text_input()
                else:
                    self.answer(action)
            if handled:
                return
        if event.type == pg.KEYDOWN and event.key == pg.K_TAB:
            self._set_transcript(True)
            return
        if event.type == pg.KEYDOWN and event.key in (pg.K_PAGEUP, pg.K_PAGEDOWN):
            self._set_transcript(True, scroll=8 if event.key == pg.K_PAGEUP else 0)
            return
        if event.type == pg.MOUSEWHEEL:
            self._finish_narration()
            position = pg.mouse.get_pos()
            if self.menu_rect.collidepoint(position):
                self.choice_scroll = max(0, self.choice_scroll - event.y * 55)
            elif self.transcript_open:
                self.history_scroll = max(0, self.history_scroll + event.y * 3)
            return
        if self.reading:
            if event.type == pg.KEYDOWN and event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                self._continue_reading()
            elif event.type == pg.KEYDOWN and event.key in (pg.K_LEFT, pg.K_BACKSPACE) and self.narrative.previous():
                self._sync_page()
                self._sync_world()
            elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1 and any(rect.collidepoint(event.pos) for rect, _ in self.choice_hits):
                self._continue_reading()
            return
        if event.type == pg.KEYDOWN and event.key == pg.K_BACKSPACE and self.request is not None and self.request.kind != "text" and self.narrative.cinematic and self.narrative.previous():
            self._sync_page()
            self._sync_world()
            return
        if self.world.active and not self.transcript_open:
            if event.type == pg.KEYDOWN and event.key in (pg.K_w, pg.K_a, pg.K_s, pg.K_d):
                # Walking also closes inspections on update. Transfer focus
                # now, so Enter/A follows the nearby prompt afterwards.
                self._menu_focused = False
            if self._menu_focused and not self.world.inspection_open and event.type == pg.KEYDOWN and event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE, pg.K_RIGHT):
                self._choose(self.selected + 1)
                return
            was_inspecting = self.world.inspection_open
            handled, answer = self.world.handle_event(event)
            if self.world.inspection_open and not was_inspecting:
                self._record_world_inspection()
                self.soundscape.play_effect("interact")
            if answer is not None:
                self.soundscape.play_effect("interact")
                self.answer(answer)
            if handled:
                if event.type in (pg.KEYDOWN, pg.MOUSEBUTTONDOWN) and not self.world.inspection_open:
                    self._menu_focused = False
                return
        if self._combat_active and self.request is not None and self.request.kind == "combat":
            if event.type == pg.KEYDOWN and event.key in (pg.K_LEFTBRACKET, pg.K_RIGHTBRACKET) and self.battle.snapshot:
                targets = [enemy.id for enemy in self.battle.snapshot.enemies if enemy.hp > 0]
                if targets:
                    current = targets.index(self.battle.snapshot.target_id) if self.battle.snapshot.target_id in targets else 0
                    step = -1 if event.key == pg.K_LEFTBRACKET else 1
                    self.answer(CombatCommand("target", targets[(current + step) % len(targets)]))
                return
            handled, target = self.battle.handle_event(event)
            if target is not None:
                self.answer(CombatCommand("target", target))
            if handled:
                return
        if (event.type == pg.MOUSEBUTTONDOWN and event.button == 1
                and self.request is not None and self.request.kind == "text"
                and self._name_keyboard_hit.collidepoint(event.pos)):
            self._open_name_keyboard()
            return
        if event.type == pg.MOUSEMOTION:
            hovered = next((answer - 1 for rect, answer in self.choice_hits if isinstance(answer, int) and rect.collidepoint(event.pos)), None)
            if hovered is not None:
                self._menu_focused = True
                if hovered != self.selected:
                    self.selected = hovered
                    self.soundscape.play_effect("hover")
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            for rect, answer in self.choice_hits + self.utility_hits:
                if rect.collidepoint(event.pos):
                    if self.request and self.request.kind == "text" and answer is not None:
                        self.answer(self.entry)
                    else:
                        self._choose(answer) if isinstance(answer, int) else self.answer(answer)
                    return
        request = self.request
        if request is None:
            if self.finished and event.type == pg.KEYDOWN and event.key in (pg.K_RETURN, pg.K_ESCAPE):
                self.ui.close()
            return
        if request.kind == "text":
            if event.type == pg.TEXTEDITING:
                self.entry_composition = "".join(character for character in str(event.text) if character.isprintable())
            elif event.type == pg.TEXTINPUT:
                self._entry_editor.insert(event.text)
                self.entry_composition = ""
            elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1 and self._entry_field.collidepoint(event.pos):
                if getattr(event, "clicks", 1) > 1:
                    self._entry_editor.select_all()
                else:
                    visible = self.entry[self._entry_view_start:self._entry_view_end]
                    advances = caret_positions(self.font, visible)
                    closest = self._entry_view_start + min(range(len(advances)), key=lambda index: abs(self._entry_text_x + advances[index] - event.pos[0]))
                    self._entry_editor.move_to(closest, select=bool(pg.key.get_mods() & pg.KMOD_SHIFT))
            elif event.type == pg.KEYDOWN:
                modifiers = getattr(event, "mod", 0)
                command = bool(modifiers & (pg.KMOD_CTRL | pg.KMOD_GUI))
                select = bool(modifiers & pg.KMOD_SHIFT)
                if self.entry_composition and (event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_BACKSPACE, pg.K_DELETE, pg.K_LEFT, pg.K_RIGHT, pg.K_HOME, pg.K_END) or event.key == pg.K_a and command):
                    return
                if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                    self.answer(self.entry)
                elif event.key == pg.K_BACKSPACE:
                    self._entry_editor.backspace(word=command)
                elif event.key == pg.K_DELETE:
                    self._entry_editor.delete(word=command)
                elif event.key in (pg.K_LEFT, pg.K_RIGHT):
                    self._entry_editor.navigate(-1 if event.key == pg.K_LEFT else 1, select=select, word=command)
                elif event.key in (pg.K_HOME, pg.K_END):
                    move = self._entry_editor.home if event.key == pg.K_HOME else self._entry_editor.end
                    move(select=select)
                elif event.key == pg.K_a and command:
                    self._entry_editor.select_all()
                elif event.key == pg.K_ESCAPE:
                    if self.entry_composition:
                        self.entry_composition = ""
                    elif request.allow_back:
                        self.answer(None)
            return
        if event.type != pg.KEYDOWN:
            return
        key = event.key
        if request.kind == "pause":
            if key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                self.answer("")
            return
        character = getattr(event, "unicode", "").lower()
        if request.story and key == pg.K_F5:
            self.answer("s")
        elif request.story and key == pg.K_F1:
            self.answer("h")
        elif request.story and character in dict(STORY_COMMANDS) and not (self.world.active and character == "s"):
            self.answer(character)
        elif key == pg.K_ESCAPE and (request.story or request.allow_back):
            self.answer("p" if request.story else None)
        elif key in (pg.K_UP, pg.K_w, pg.K_k):
            self._menu_focused = True
            self.selected = (self.selected - 1) % len(request.options)
            self._keep_selection_visible()
        elif key in (pg.K_DOWN, pg.K_s):
            self._menu_focused = True
            self.selected = (self.selected + 1) % len(request.options)
            self._keep_selection_visible()
        elif key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE, pg.K_RIGHT, pg.K_d):
            self._choose(self.selected + 1)
        elif request.allow_back and key in (pg.K_LEFT, pg.K_a, pg.K_b):
            self.answer(None)
        elif (number := choice_number(character, len(request.options))) is not None:
            self._choose(number)

    def _choose(self, answer: int) -> None:
        if self.request and self.request.kind == "combat" and self.battle.snapshot:
            actions = self.battle.snapshot.actions
            if 0 < answer <= len(actions) and self.battle.busy and actions[answer - 1].id not in {"target", "inspect"}:
                return
            if 0 < answer <= len(actions) and not actions[answer - 1].enabled:
                self._toast(actions[answer - 1].disabled_reason or "That action is unavailable.")
                return
            if 0 < answer <= len(actions):
                self._turn_summary = self._turn_summary.begin_action(actions[answer - 1])
        self.answer(answer)

    def _choice_dimensions(self) -> list[tuple[int, list[str]]]:
        if self.request is None:
            return []
        width = max(70, self.menu_rect.width - 54)
        return [(max(50, len(lines) * self.line_height + 24), lines) for option in self.request.options for lines in [wrap_pixels(option, self.font, width)]]

    def _keep_selection_visible(self) -> None:
        dimensions = self._choice_dimensions()
        if not dimensions:
            return
        top = sum(height + 10 for height, _ in dimensions[:self.selected])
        bottom = top + dimensions[self.selected][0]
        viewport = max(1, self.menu_rect.height)
        if bottom - top > viewport or top < self.choice_scroll:
            self.choice_scroll = top
        elif bottom > self.choice_scroll + viewport:
            self.choice_scroll = bottom - viewport

    def _text(self, text: str, position: tuple[int, int], color: Any = PARCHMENT, font: Any = None) -> None:
        self.screen.blit((font or self.font).render(text, False, color), position)

    def _panel(self, rect: Any, color: Any = PANEL, *, ornate: bool = False) -> None:
        draw_pixel_frame(self.pg, self.screen, rect, fill=color, edge=TEAL, accent=AMBER, ornate=ornate)

    def _sync_fonts(self, width: int) -> None:
        extra = 7 if width >= 2500 else 4 if width >= 1800 else 2 if width >= 1400 else 0
        preference = {"standard": 0, "large": 3, "larger": 6}.get(self.ui.text_size, 0)
        key = (17 + extra + preference, 13 + min(4, extra), 24 + extra)
        if key == self._font_key:
            return
        self.font = load_font(self.pg, key[0])
        self.small_font = load_font(self.pg, key[1])
        self.title_font = load_font(self.pg, key[2], bold=True)
        self._font_key = key
        self.line_height = self.font.get_linesize() + 3
        self._history_layout_key = None
        self._layout_size = None

    def render(self) -> None:
        if self.minimized:
            return
        pg = self.pg
        width, height = self.screen.get_size()
        self._sync_fonts(width)
        now = pg.time.get_ticks()
        elapsed = max(0, now - self._frame_tick) / 1000
        dt = min(0.25, elapsed)
        self._frame_tick = now
        self._advance_narration()
        walking_context = (self.world.active and not self.reading and not self.panels.active
                           and not self.transcript_open and not self.name_keyboard.active)
        for action in self.gamepad.update(dt, stick_navigation=not walking_context):
            self._dispatch_pad(action)
        if self._layout_size != (width, height):
            self._layout_size = (width, height)
            _, rows, text_width = self._reading_dimensions()
            self._reflow_narrative(rows=rows, width=text_width)
            self._sync_world()
        if self.world.active and not self.panels.active and not self.transcript_open and not self.name_keyboard.active:
            before = self.world.player_position
            movement = self.gamepad.movement
            if movement != (0.0, 0.0):
                self._menu_focused = False
            self.world.update(dt, reduced_motion=self.ui.reduced_motion, movement_vector=movement)
            focused = self.world.focused_option
            if not self._menu_focused and focused is not None:
                self.selected = focused - 1
                self._keep_selection_visible()
            if self.world.player_position != before:
                self.soundscape.play_effect("footstep", surface=self.world.surface_kind)
        if self._combat_active and not self.reading and not self.panels.active and not self.transcript_open:
            self.battle.update(dt, reduced_motion=self.ui.reduced_motion)
        in_menu = self.request is not None and self.request.label == "MAIN MENU"
        audio_scene = None if in_menu else (self.world.map_key if self.world.active else (self.hud.get("scene") if self.hud else self.scene_key))
        self.soundscape.set_scene(audio_scene, combat=self._combat_active)
        self.soundscape.update(dt, enabled=self.ui.sound_enabled, music_volume=self.ui.music_volume, sfx_volume=self.ui.sfx_volume)
        for cue in self.battle.drain_cues():
            self.soundscape.play_effect(cue)
        self.screen.fill(INK)
        margin = 22 if width >= 1000 else 15
        gap = 18
        left_width = int((width - margin * 2 - gap) * 0.60)
        right_x = margin + left_width + gap
        right_width = width - right_x - margin
        self._text("ROADS BENEATH THE SHADOW", (margin, 18), AMBER, self.title_font)
        self._text("PIXEL EDITION  /  PARTS I & II", (margin, 49), TEAL, self.small_font)
        if self.hud:
            hud = self.hud
            hp, max_hp = hud['hp'], hud['max_hp']
            focus, max_focus = hud['focus'], hud['max_focus']
            if self._combat_active and not self.reading and self.battle.snapshot is not None:
                visible_health = self.battle.displayed_player_health
                if visible_health is not None:
                    hp, max_hp = visible_health
                focus, max_focus = self.battle.snapshot.player.focus, self.battle.snapshot.player.max_focus
            name = hud['name']
            suffix = f"  |  Part {hud['chapter']}"
            if self.small_font.size(name + suffix)[0] > right_width:
                clusters = list(text_clusters(name))
                while clusters and self.small_font.size("".join(clusters) + "…" + suffix)[0] > right_width:
                    clusters.pop()
                name = "".join(clusters)
                name += "…"
            self._text(name + suffix, (right_x, 19), PARCHMENT, self.small_font)
            self._text(f"HP {hp}/{max_hp}   FOCUS {focus}/{max_focus}", (right_x, 40), TEAL, self.small_font)
            meter_width = max(60, (right_width - 12) // 2)
            for x, value, maximum, color in ((right_x, hp, max_hp, AMBER), (right_x + meter_width + 12, focus, max_focus, TEAL)):
                pg.draw.rect(self.screen, PANEL, (x, 59, meter_width, 5))
                pg.draw.rect(self.screen, color, (x, 59, int(meter_width * max(0, min(1, value / max(1, maximum)))), 5))
            self._text(f"HOPE {hud['hope']}   SHADOW {hud['corruption']}", (right_x, 70), MUTED, self.small_font)
        top = 87
        available = height - top - 45
        art_height, _, _ = self._reading_dimensions()
        if self._combat_active and not self.reading:
            art_height = min(available - (96 if height < 700 else 130), max(art_height, 420))
        self.art_rect = pg.Rect(margin, top, left_width, art_height)
        self._panel(self.art_rect, ornate=True)
        inner = self.art_rect.inflate(-8, -8)
        if self.world.active and not self.reading:
            self.world.draw(self.screen, inner, now_ms=now, reduced_motion=self.ui.reduced_motion,
                            text_size=self.ui.text_size, preview_answer=self.selected + 1 if self._menu_focused else None)
        elif self._combat_active and not self.reading and self.battle.snapshot is not None:
            backdrop_key = BATTLE_BACKDROPS.get((self.hud or {}).get("scene"))
            self.battle.set_scene(self._battle_backdrop(), ground_y=BATTLE_GROUND_Y.get(backdrop_key))
            self.battle.draw(self.screen, inner, now, text_size=self.ui.text_size)
        elif self.scene is not None:
            sw, sh = self.scene.get_size()
            # Integer enlargement at the default size; smaller windows still
            # use nearest-neighbor scaling to keep every edge crisp.
            scale = min(inner.width / sw, inner.height / sh)
            if scale >= 2:
                scale = int(scale)
            target = (max(1, int(sw * scale)), max(1, int(sh * scale)))
            cache_key = (self.scene_key, target)
            picture = self._scaled_scenes.pop(cache_key, None)
            if picture is None:
                picture = pg.transform.scale(self.scene, target)
                self._scaled_scenes[cache_key] = picture
                while len(self._scaled_scenes) > 1 and (
                    len(self._scaled_scenes) > 24 or
                    sum(surface.get_pitch() * surface.get_height() for surface in self._scaled_scenes.values()) > SCENE_CACHE_BYTES
                ):
                    self._scaled_scenes.pop(next(iter(self._scaled_scenes)))
            else:
                self._scaled_scenes[cache_key] = picture
            picture_rect = picture.get_rect(center=inner.center)
            self.screen.blit(picture, picture_rect)
            if self.ui.motion_enabled:
                self._ambient_pixels(picture_rect, scale)
        else:
            self._fallback_star(inner)
        self.history_rect = pg.Rect(margin, self.art_rect.bottom + gap, left_width, available - art_height - gap)
        self._panel(self.history_rect, ornate=True)
        self._render_history()
        right = pg.Rect(right_x, top, right_width, available)
        self._panel(right, ornate=True)
        label = "Resolving the encounter" if self._battle_transition_hold else (self.heading if self.reading else (self.request.label if self.request is not None else (("THE JOURNEY STOPPED" if self.error else "JOURNEY COMPLETE") if self.finished else self.heading)))
        label_lines = wrap_pixels(label.strip(), self.font, right.width - 32)
        label_y = right.top + 17
        for line in label_lines:
            self._text(line, (right.left + 16, label_y), AMBER)
            label_y += self.line_height
        pg.draw.line(self.screen, TEAL, (right.left + 16, label_y + 7), (right.right - 16, label_y + 7))
        self.menu_rect = pg.Rect(right.left + 12, label_y + 22, right.width - 24, max(50, right.bottom - label_y - 44))
        self.choice_hits = []
        self.utility_hits = []
        self._name_keyboard_hit = pg.Rect(0, 0, 0, 0)
        request = self.request
        if self.reading:
            page = self.narrative.current
            self._text(f"STORY  {page.number}/{page.total}", (self.menu_rect.left + 4, self.menu_rect.top + 8), TEAL, self.small_font)
            self._render_continue("Continue reading" if self._page_finished else "Reveal text", self.menu_rect.top + 40)
            self._text("Return or Space to continue", (self.menu_rect.left + 4, self.menu_rect.top + 105), MUTED, self.small_font)
            if self.narrative.has_previous:
                self._text("Left arrow: previous page", (self.menu_rect.left + 4, self.menu_rect.top + 128), MUTED, self.small_font)
        elif request is not None and request.story:
            utility_height = 122
            self.menu_rect.height = max(50, self.menu_rect.height - utility_height)
            self._render_utilities(right)
        elif request is not None and request.allow_back:
            self.menu_rect.height = max(50, self.menu_rect.height - 52)
            back = pg.Rect(right.left + 16, right.bottom - 53, right.width - 32, 38)
            self._panel(back)
            self._text("[ESC] Back", (back.left + 12, back.top + 10), TEAL, self.small_font)
            self.utility_hits.append((back, None))
        if not self.reading and request is not None and request.kind == "combat" and self.battle.snapshot:
            self._render_action_details(right)
        if not self.reading and request is not None and request.kind in {"choice", "combat"}:
            self._render_choices()
        elif not self.reading and request is not None and request.kind == "text":
            field = pg.Rect(self.menu_rect.left + 4, self.menu_rect.top + 15, self.menu_rect.width - 8, 58)
            self._render_name_entry(field)
            self._render_continue("Begin the road", field.bottom + 21)
            limit = request.context.get("max_length", 64)
            self._text(f"1–{limit} printable characters", (field.left + 3, field.bottom + 86), MUTED, self.small_font)
            self._text("Ctrl/Cmd+A selects all", (field.left + 3, field.bottom + 105), MUTED, self.small_font)
            self._name_keyboard_hit = pg.Rect(field.left, field.bottom + 134, field.width, 36)
            self._panel(self._name_keyboard_hit)
            self._text("On-screen keyboard", (self._name_keyboard_hit.left + 10,
                                              self._name_keyboard_hit.top + 10), TEAL, self.small_font)
        elif not self.reading and request is not None and request.kind == "pause":
            self._render_continue("Continue", self.menu_rect.top + 12)
        elif self.finished:
            if self.error:
                self._text("Details are in Archive.", (self.menu_rect.left + 6, self.menu_rect.top + 22), PARCHMENT, self.small_font)
            else:
                self._text("May a star shine", (self.menu_rect.left + 6, self.menu_rect.top + 22), TEAL)
                self._text("upon your road.", (self.menu_rect.left + 6, self.menu_rect.top + 47), TEAL)
            self._text("Return or Esc to close", (self.menu_rect.left + 6, self.menu_rect.top + 95), MUTED, self.small_font)
        if self.reading:
            footer = "SPACE / ENTER Read   BACKSPACE Previous   TAB Archive   F1 Controls   F11 Fullscreen"
        elif request is not None and request.kind == "text":
            footer = "TYPE Name   ARROWS Cursor   ENTER Continue   TAB Archive   F1 Controls   F11 Fullscreen"
        elif self.world.active:
            footer = "WASD Walk   E Interact   F5 Save slots   TAB Archive   F1 Controls   F11 Fullscreen"
        elif self._combat_active:
            footer = "ARROWS Select   ENTER Act   [ / ] Target   TAB Archive   F1 Controls   F11 Fullscreen"
        else:
            footer = "ARROWS Select   ENTER Confirm   1-9 Choose   TAB Archive   F1 Controls   F11 Fullscreen"
        if self.gamepad.available:
            if self.panels.active or self.transcript_open:
                footer = "D-pad / Stick Navigate   A Select   B Close   LB / RB Scroll"
            elif self.reading:
                footer = "A Read   B Previous page   View Archive   F1 Controls"
            elif request is not None and request.kind == "text":
                footer = "A Continue   X Naming keyboard   B Back   View Archive"
            elif self.world.active:
                footer = "Stick Walk   D-pad Choices   A Interact / Choose   Menu Pause"
            elif self._combat_active:
                footer = "D-pad Actions   A Act   X Inspect   LB / RB Target   View Archive"
            else:
                footer = "D-pad / Stick Select   A Confirm   B Back   View Archive"
        if self.small_font.size(footer)[0] > width - margin * 2:
            footer = footer.replace("   ", "  ").replace("F11 Fullscreen", "F11 Full").replace("TAB Archive", "TAB Log").replace("F1 Controls", "F1 Help")
        while self.small_font.size(footer)[0] > width - margin * 2 and len(footer) > 1:
            footer = footer[:-2].rstrip("…") + "…"
        self._text(footer, (margin, height - 26), MUTED, self.small_font)
        # The compact battle canvas has no spare banner area: stacking notices
        # over its cards hides Health and Armor. Keep their remaining display
        # time until the encounter ends, as with an open exploration inspection.
        defer_toasts = self.world.inspection_open or (
            self._combat_active and not self.reading and self.battle.snapshot is not None
        )
        if self._toasts_deferred:
            pause_start = now / 1000 - elapsed
            self._toasts[:] = [
                (text, min(now / 1000 + 4.0, expires + elapsed))
                for text, expires in self._toasts if expires > pause_start
            ]
        self._toasts_deferred = defer_toasts
        self._toasts[:] = [(text, expires) for text, expires in self._toasts if expires > now / 1000]
        toast_bottom = self.art_rect.bottom - 12
        for text, _ in reversed(self._toasts if not defer_toasts else []):
            lines = wrap_pixels(text, self.small_font, min(520, self.art_rect.width - 48))
            toast_width = max(self.small_font.size(line)[0] for line in lines) + 28
            toast = pg.Rect(self.art_rect.right - toast_width - 12, toast_bottom - 18 - len(lines) * 17, toast_width, 18 + len(lines) * 17)
            toast_bottom = toast.top - 8
            self._panel(toast, INK)
            for row, line in enumerate(lines):
                self._text(line, (toast.x + 13, toast.y + 8 + row * 17), AMBER, self.small_font)
        if self.panels.active or self.transcript_open or self.name_keyboard.active:
            shade = pg.Surface((width, height), pg.SRCALPHA)
            shade.fill((6, 10, 15, 205))
            self.screen.blit(shade, (0, 0))
            modal_rect = pg.Rect(margin + 8, 75, width - margin * 2 - 16, height - 113)
            if self.name_keyboard.active:
                self.name_keyboard.draw(self.screen, modal_rect, self.font, self.small_font, self.entry)
            elif self.transcript_open:
                self.archive.set_entries(self.history)
                self.archive.draw(self.screen, modal_rect, text_size=self.ui.text_size)
                self.history_scroll = self.archive.scroll
            else:
                self.panels.draw(self.screen, modal_rect, text_size=self.ui.text_size)
        if not self.ui.color:
            self.screen.blit(pg.transform.grayscale(self.screen), (0, 0))
        pg.display.flip()

    def _ambient_pixels(self, rect: Any, scale: float) -> None:
        """A few scene-specific pixels breathe without moving the illustration."""
        pg = self.pg
        tick = pg.time.get_ticks()
        pixel = max(1, int(scale))
        self.screen.set_clip(rect)
        if self.scene_key in {"title", "seal"}:
            points = ((0.18, 0.17), (0.77, 0.12), (0.32, 0.09), (0.87, 0.29), (0.11, 0.33))
            for index, (x, y) in enumerate(points):
                if (tick // 470 + index * 2) % 7 < 2:
                    pg.draw.rect(self.screen, AMBER, (rect.left + int(x * rect.width), rect.top + int(y * rect.height), pixel, pixel))
        elif self.scene_key in {"camp", "lantern"}:
            for index in range(4):
                rise = (tick // 120 + index * 9) % 35
                x = rect.centerx + (index * 13 % 31 - 15) * pixel
                y = rect.top + int(rect.height * 0.76) - rise * pixel
                pg.draw.rect(self.screen, AMBER if rise < 18 else (137, 102, 69), (x, y, pixel, pixel))
        elif self.scene_key in {"tavern", "marsh", "rider"}:
            for index in range(7):
                x = rect.left + int(((index * 47 + 19) % 100) / 100 * rect.width)
                y = rect.top + ((tick // 70 + index * 43) * pixel) % rect.height
                pg.draw.rect(self.screen, (81, 108, 116), (x, y, pixel, 3 * pixel))
        self.screen.set_clip(None)

    def _fallback_star(self, rect: Any) -> None:
        pg = self.pg
        cx, cy = rect.center
        cy -= 20
        for angle in ((0, -55), (0, 55), (-55, 0), (55, 0), (-30, -30), (30, 30), (-30, 30), (30, -30)):
            dx, dy = angle
            pg.draw.polygon(self.screen, AMBER, [(cx + dx, cy + dy), (cx - 5, cy - 5), (cx + 5, cy + 5)])
        pg.draw.polygon(self.screen, TEAL, [(cx - 170, rect.bottom - 35), (cx - 95, cy + 45), (cx - 25, rect.bottom - 35)])
        pg.draw.polygon(self.screen, TEAL, [(cx + 25, rect.bottom - 35), (cx + 105, cy + 45), (cx + 170, rect.bottom - 35)])

    def _render_history(self) -> None:
        rect = self.history_rect
        if self.transcript_open:
            return
        if not self.transcript_open and self._combat_active and not self.reading and self.battle.snapshot:
            self._text("BATTLE LOG  /  CLICK A FOE TO TARGET", (rect.left + 16, rect.top + 8), TEAL, self.small_font)
            snapshot = self.battle.snapshot
            entries = self._battle_log or [("Your turn. Read their intent before committing your move.", None, False)]
            lines = [(line, color) for text, color, _ in entries for line in wrap_pixels(text, self.font, rect.width - 40)]
            rows = max(1, (rect.height - 49) // self.line_height)
            if rows <= 2:
                columns = max(8, (rect.width - 40) // max(1, self.small_font.size("M")[0]))
                first, second = self._turn_summary.lines(snapshot, max_columns=columns)
                incoming = any(event.kind in {"damage", "info"} and event.target_id == "player" and event.amount > 0 for event in self._turn_summary.feedback)
                self.screen.set_clip(rect.inflate(-12, -12))
                self._text(first, (rect.left + 16, rect.top + 29), PARCHMENT, self.small_font)
                self._text(second, (rect.left + 16, rect.top + 29 + self.small_font.get_linesize() + 3), RED if incoming else TEAL, self.small_font)
                self.screen.set_clip(None)
                return
            self.screen.set_clip(rect.inflate(-12, -12))
            for index, (line, color) in enumerate(lines[-rows:]):
                self._text(line, (rect.left + 16, rect.top + 29 + index * self.line_height), TEAL if color == Color.GREEN else PARCHMENT)
            self.screen.set_clip(None)
            return
        if not self.transcript_open and self.narrative.current is not None:
            page = self.narrative.current
            self._text("STORY" + (f"  {page.number}/{page.total}" if page.total > 1 else ""), (rect.left + 16, rect.top + 8), TEAL, self.small_font)
            color_map = {Color.YELLOW: AMBER, Color.CYAN: TEAL, Color.GREEN: TEAL, Color.RED: RED, Color.MAGENTA: (171, 145, 195), Color.DIM: MUTED}
            remaining = int(self._page_reveal)
            self.screen.set_clip(rect.inflate(-12, -12))
            for index, line in enumerate(page.lines):
                text = line.text[:max(0, remaining)]
                remaining -= len(line.text) + 1
                self._text(text, (rect.left + 16, rect.top + 29 + index * self.line_height), color_map.get(line.color, PARCHMENT))
            self.screen.set_clip(None)
            if self.world.active and not self.world.inspection_open:
                hint = self.world.hint_text
                self._text(hint[:max(1, (rect.width - 32) // 8)], (rect.left + 16, rect.bottom - 20), AMBER, self.small_font)
            return
        key = (len(self.history), rect.width, tuple((index, int(count)) for index, count in self._reveals.items()))
        if key != self._history_layout_key:
            self._text_layout = []
            for index, (text, color, bold) in enumerate(self.history):
                if index in self._reveals:
                    text = text[:int(self._reveals[index])]
                self._text_layout.extend((line, color, bold) for line in wrap_pixels(text, self.font, rect.width - 40))
            self._history_layout_key = key
        rows = max(1, (rect.height - 40) // self.line_height)
        maximum_scroll = max(0, len(self._text_layout) - rows)
        self.history_scroll = min(self.history_scroll, maximum_scroll)
        end = len(self._text_layout) - self.history_scroll
        start = max(0, end - rows)
        color_map = {Color.YELLOW: AMBER, Color.CYAN: TEAL, Color.GREEN: TEAL, Color.RED: RED, Color.MAGENTA: (171, 145, 195), Color.DIM: MUTED}
        self.screen.set_clip(rect.inflate(-12, -12))
        y = rect.top + 15
        for line, color, _bold in self._text_layout[start:end]:
            self._text(line, (rect.left + 16, y), color_map.get(color, PARCHMENT))
            y += self.line_height
        self.screen.set_clip(None)

    def _finish_narration(self) -> None:
        self._reveals.clear()
        self._history_layout_key = None
        self._page_reveal = float(len(self.narrative.current.text) if self.narrative.current else 0)
        self._remember_page()

    def _advance_narration(self) -> None:
        now = self.pg.time.get_ticks()
        elapsed = max(0, now - self._last_tick) / 1000
        self._last_tick = now
        if self._local_help:
            return
        delay = self.ui.narration_delay
        if self.narrative.current and not self._page_finished:
            self._page_reveal = float(len(self.narrative.current.text)) if not delay or self.ui.reduced_motion else min(len(self.narrative.current.text), self._page_reveal + elapsed * (5.0 / delay))
            if self._page_finished:
                self._remember_page()
                self._sync_world()

    def _render_choices(self) -> None:
        # Action help and reading-size changes can alter the final viewport
        # after a navigation event. Refit the focused choice once for that
        # new layout, while leaving ordinary wheel browsing free to scroll.
        view_key = (self.request.identifier if self.request else None,
                    self._font_key, self.menu_rect.size, self.selected)
        if view_key != self._choice_view_key:
            self._choice_view_key = view_key
            if self._menu_focused:
                self._keep_selection_visible()
        dimensions = self._choice_dimensions()
        total = sum(height + 10 for height, _ in dimensions) - 10
        self.choice_scroll = min(self.choice_scroll, max(0, total - self.menu_rect.height))
        self.screen.set_clip(self.menu_rect)
        y = self.menu_rect.top - self.choice_scroll
        for index, (height, lines) in enumerate(dimensions):
            rect = self.pg.Rect(self.menu_rect.left + 3, y, self.menu_rect.width - 6, height)
            selected = index == self.selected
            action = self.battle.snapshot.actions[index] if self.request and self.request.kind == "combat" and self.battle.snapshot and index < len(self.battle.snapshot.actions) else None
            enabled = action is None or (action.enabled and (not self.battle.busy or action.id in {"target", "inspect"}))
            self._panel(rect, (39, 49, 50) if selected else INK)
            if selected:
                self.pg.draw.rect(self.screen, AMBER, (rect.left, rect.top, 4, rect.height))
            self._text(str(index + 1).zfill(2), (rect.left + 12, rect.top + 13), AMBER if selected else TEAL, self.small_font)
            for line_number, line in enumerate(lines):
                self._text(line, (rect.left + 39, rect.top + 12 + line_number * self.line_height), PARCHMENT if enabled else MUTED)
            clipped = rect.clip(self.menu_rect)
            if clipped.height > 0:
                self.choice_hits.append((clipped, index + 1))
            y += height + 10
        self.screen.set_clip(None)
        if total > self.menu_rect.height:
            self._text("Scroll or use arrows for more", (self.menu_rect.left + 5, self.menu_rect.bottom + 4), TEAL, self.small_font)

    def _render_action_details(self, right: Any) -> None:
        actions = self.battle.snapshot.actions
        if not actions:
            return
        action = actions[min(self.selected, len(actions) - 1)]
        descriptions = tuple(item.description if item.enabled else item.disabled_reason or "Unavailable."
                             for item in actions)
        layout_key = (self._font_key, right.width, descriptions)
        if layout_key != self._combat_help_layout_key:
            self._combat_help_layout_key = layout_key
            self._combat_help_lines = tuple(wrap_pixels(text, self.small_font, right.width - 42)
                                            for text in descriptions)
        lines = self._combat_help_lines[min(self.selected, len(actions) - 1)]
        # Reserve the same help band for every command. Hover must not move a
        # partially visible button away from the pointer before its click.
        row_step = max(17, self.small_font.get_linesize() + 2)
        rows = max(map(len, self._combat_help_lines))
        height = 26 + row_step + rows * row_step + self.small_font.get_height()
        dock = self.pg.Rect(right.left + 16, right.bottom - height - 12, right.width - 32, height)
        self.menu_rect.height = max(50, dock.top - self.menu_rect.top - 22)
        self._panel(dock, INK)
        cost = f"{action.focus_cost} Focus" if action.focus_cost else "No Focus cost"
        self._text(cost + ("  ·  Free look" if action.id in {"inspect", "target"} else ""), (dock.x + 10, dock.y + 9), TEAL, self.small_font)
        for row, line in enumerate(lines):
            self._text(line, (dock.x + 10, dock.y + 12 + row_step + row * row_step), PARCHMENT if action.enabled else MUTED, self.small_font)
        hint = "Let the impacts land…" if self.battle.busy else "[ / ] Target  ·  Tab Log"
        self._text(hint, (dock.x + 10, dock.bottom - self.small_font.get_height() - 8), AMBER if self.battle.busy else MUTED, self.small_font)

    def _render_utilities(self, right: Any) -> None:
        button_width = (right.width - 42) // 2
        for index, (command, label) in enumerate(UTILITY_COMMANDS):
            rect = self.pg.Rect(right.left + 16 + (index % 2) * (button_width + 10), right.bottom - 111 + (index // 2) * 34, button_width, 28)
            self._panel(rect)
            shortcut = "F5" if command == "s" and self.world.active else command.upper()
            self._text(f"[{shortcut}] {label}", (rect.left + 7, rect.top + 8), TEAL, self.small_font)
            self.utility_hits.append((rect, command))

    def _render_continue(self, label: str, y: int) -> None:
        rect = self.pg.Rect(self.menu_rect.left + 4, y, self.menu_rect.width - 8, 49)
        self._panel(rect, (39, 49, 50))
        self._text(label, (rect.left + 15, rect.top + 15), AMBER)
        self.choice_hits.append((rect, self.entry if self.request and self.request.kind == "text" else ""))

    def _render_name_entry(self, field: Any) -> None:
        pg = self.pg
        self._entry_field = field
        self._entry_text_x = field.left + 11
        self._panel(field, INK)
        pg.key.set_text_input_rect(field)
        start, end = self._entry_editor.selection
        text = self.entry
        caret = self._entry_editor.cursor
        if self.entry_composition:
            text = text[:start] + self.entry_composition + text[end:]
            caret = start + len(self.entry_composition)
        available = max(1, field.width - 24)
        view_start, visible_end = text_viewport(self.font, text, available, caret,
                                               preferred_start=self._entry_view_start,
                                               caret_padding=self.font.size(" ")[0])
        self._entry_view_start = view_start
        self._entry_view_end = visible_end
        visible = text[view_start:visible_end]
        advances = caret_positions(self.font, visible)
        position = lambda offset: advances[max(0, min(len(visible), offset - view_start))]
        x = self._entry_text_x
        y = field.top + 19
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(field.inflate(-12, -8))
        if self._entry_editor.has_selection and not self.entry_composition:
            left, right = x + position(start), x + position(end)
            if min(end, visible_end) > max(start, view_start):
                pg.draw.rect(self.screen, (42, 63, 66), (left, y - 2, max(2, right - left), self.font.get_linesize() + 3))
        self._text(visible, (x, y))
        caret_x = x + position(caret)
        if self.entry_composition:
            left = x + position(start)
            pg.draw.line(self.screen, TEAL, (left, y + self.font.get_linesize()), (caret_x, y + self.font.get_linesize()))
        if self.entry_composition or (pg.time.get_ticks() // 500) % 2 == 0:
            pg.draw.line(self.screen, AMBER, (caret_x, y), (caret_x, y + self.font.get_height()), 2)
        self.screen.set_clip(previous_clip)


def launch_pixel_game(game: Any, ui: PixelUI, *, screenshot: Path | None = None) -> None:
    """Run the unchanged Game with a responsive graphical display."""
    window = PixelWindow(ui, size=(1200, 900) if screenshot is not None else None)
    ui.state_provider = lambda: game.state

    def story_worker() -> None:
        error = None
        try:
            game.run()
        except (InputClosed, KeyboardInterrupt):
            return
        except Exception as exception:
            error = f"The journey stopped: {exception}"
        finally:
            # Completion is also delivered after close; no renderer calls run
            # on this worker even during exception handling.
            ui.events.put(UIEvent("finished", {"error": error}))

    worker = threading.Thread(target=story_worker, name="roads-story", daemon=True)
    worker.start()
    try:
        screenshot_frames = 0
        while not ui.closed.is_set():
            window.drain()
            for event in window.pg.event.get():
                window.handle_event(event)
            window.render()
            if screenshot is not None and window.request is not None and not window.minimized:
                screenshot_frames += 1
                if screenshot_frames >= 2:
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    window.pg.image.save(window.screen, str(screenshot))
                    ui.close()
            window.clock.tick(15 if window.minimized else 60)
    finally:
        ui.close()
        worker.join(timeout=1.0)
        window.gamepad.close()
        window.pg.quit()
