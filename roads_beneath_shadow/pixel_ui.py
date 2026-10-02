"""Pixel-art presentation of the complete story engine.

The story runs in a worker and only communicates through queues.  Pygame and
its display, font, and input APIs stay on the calling (main) thread.
"""

from __future__ import annotations

import re
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from .lighting import Color
from .narrative import NarrativeDirector
from .combat_view import CombatCommand
from .pixel_battle import BattleView
from .pixel_panels import PanelView
from .pixel_world import WorldView
from .player_view import player_snapshot
from .soundscapes import SoundscapePlayer
from .ui import InputClosed, TerminalUI


INK = (16, 21, 27)
PANEL = (23, 31, 38)
PARCHMENT = (239, 225, 188)
AMBER = (219, 168, 92)
TEAL = (105, 156, 151)
MUTED = (159, 161, 150)
RED = (219, 132, 113)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
STORY_COMMANDS = (("i", "Inventory"), ("c", "Character"), ("j", "Journal"), ("s", "Save"), ("r", "Road map"), ("m", "Main menu"))


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
        self.events.put(UIEvent(kind, data))

    def _request(self, kind: str, label: str, options: Sequence[str] = (), *, allow_back: bool = False, story: bool = False, context: dict[str, Any] | None = None) -> Any:
        if self.closed.is_set():
            raise InputClosed
        self._request_number += 1
        hud = self._hud_snapshot()
        request_context = dict(context or {})
        if hud:
            request_context.setdefault("companions", hud["companions"])
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
        return player_snapshot(self.state_provider())

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

    def choose_story(self, heading: str, options: Sequence[str]) -> int | str | None:
        if not options:
            raise ValueError("choose_story requires at least one option")
        return self._request("choice", heading, options, story=True)

    def combat_snapshot(self, snapshot: Any) -> None:
        self._post("combat_snapshot", snapshot=snapshot)

    def combat_feedback(self, feedback: Any) -> None:
        self._post("combat_feedback", feedback=feedback)

    def choose_combat(self, options: Sequence[str]) -> Any:
        return self._request("combat", "Choose your action", options)

    def show_panel(self, kind: str, data: dict[str, Any]) -> Any:
        return self._request("panel", kind.title(), context={"kind": kind, "data": data})

    def toast(self, text: str, *, kind: str = "notice") -> None:
        self._post("toast", text=text, toast_kind=kind)

    def prompt(self, label: str = "> ") -> str:
        return str(self._request("text", label)).strip()

    def pause(self, message: str = "Press Return to continue...") -> None:
        self._request("pause", message)

    def sound(self, cue: str = "notice") -> None:
        if self.sound_enabled:
            self._post("sound", cue=cue)


def wrap_pixels(text: str, font: Any, width: int) -> list[str]:
    """Wrap to measured pixels, including unusually long names or words."""
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


class PixelWindow:
    """Main-thread renderer, exposed separately for real SDL input tests."""

    def __init__(self, ui: PixelUI, *, size: tuple[int, int] = (1200, 900)) -> None:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError as error:
            raise RuntimeError("Pixel mode needs pygame-ce. Install it with: python3 -m pip install . (or launch with --terminal)") from error
        self.pg = pygame
        self.ui = ui
        pygame.init()
        pygame.display.set_caption("Roads Beneath the Shadow — Pixel Edition")
        try:
            self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        except pygame.error as error:
            pygame.quit()
            raise RuntimeError("A graphical display could not be opened. Launch with --terminal for terminal play.") from error
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("dejavusansmono,courier,monospace", 17)
        self.small_font = pygame.font.SysFont("dejavusansmono,courier,monospace", 13)
        self.title_font = pygame.font.SysFont("dejavusansmono,courier,monospace", 24, bold=True)
        self.history: list[tuple[str, Any, bool]] = []
        self.request: InputRequest | None = None
        self.selected = 0
        self.choice_scroll = 0
        self.history_scroll = 0
        self.entry = ""
        self.entry_selected = False
        self.heading = "THE ROAD AWAITS"
        self.scene_caption = "An eight-pointed star above a winding road."
        self.hud: dict[str, Any] | None = None
        self.scene = None
        self.scene_key = "title"
        self.scene_cache: dict[str, Any] = {}
        self.choice_hits: list[tuple[Any, Any]] = []
        self.utility_hits: list[tuple[Any, str]] = []
        self.art_rect = pygame.Rect(0, 0, 0, 0)
        self.history_rect = pygame.Rect(0, 0, 0, 0)
        self.menu_rect = pygame.Rect(0, 0, 0, 0)
        self.fullscreen = False
        self.window_size = size
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
        self.soundscape = SoundscapePlayer(pygame)
        self.transcript_open = False
        self._saved_narrative: NarrativeDirector | None = None
        self._saved_journey: str | None = None
        self._page_token: Any = None
        self._page_reveal = 0.0
        self._layout_size: tuple[int, int] | None = None
        self._frame_tick = pygame.time.get_ticks()
        self._toasts: list[tuple[str, float]] = []
        self._combat_active = False
        self._battle_log: list[tuple[str, Any, bool]] = []
        self._load_scene("", "An eight-pointed star above a winding road.")

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

    def drain(self) -> None:
        while True:
            try:
                event = self.ui.events.get_nowait()
            except Empty:
                break
            data = event.data
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
                self.entry = ""
                self.entry_selected = False
                self.pg.key.start_text_input() if self.request.kind == "text" else self.pg.key.stop_text_input()
                if self.request.kind == "panel":
                    self.panels.open(self.request.context["kind"], self.request.context["data"])
                    self.world.set_request(None)
                else:
                    self.panels.close()
                    if self.request.story and self._saved_narrative is not None:
                        if self.hud and self.hud.get("journey_id") == self._saved_journey:
                            self.narrative = self._saved_narrative
                            self.narrative.discard_pending()
                        self._saved_narrative = None
                    cinematic = False if self.ui.fast else None
                    if self.request.kind == "combat" and not self._combat_active and not self.ui.fast:
                        cinematic = True
                    self._combat_active = self.request.kind == "combat" or (self.battle.snapshot is not None and self.battle.snapshot.phase == "active" and not self.request.story and self.hud is not None)
                    if self.request.label == "MAIN MENU" or self.request.story:
                        self._combat_active = False
                    _, rows, text_width = self._reading_dimensions()
                    self.narrative.prepare(self.request, wrap=lambda text: wrap_pixels(text, self.font, text_width), rows=rows, cinematic=cinematic, suppress_headers={"COMBAT"} if self.request.kind == "combat" else ())
                    self._sync_page()
                    self._sync_world()
            elif event.kind == "combat_snapshot":
                snapshot = data["snapshot"]
                if snapshot.phase == "active" and snapshot.round_number == 1 and (self.battle.snapshot is None or self.battle.snapshot.phase != "active"):
                    self._battle_log = []
                self.battle.set_snapshot(data["snapshot"])
            elif event.kind == "combat_feedback":
                feedback = data["feedback"]
                if feedback.kind == "notice":
                    self._toast(feedback.text)
                if feedback.text:
                    self._battle_log.append((feedback.text, Color.GREEN if feedback.kind in {"heal", "defend", "evade"} else None, False))
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
        return art_height, max(1, (available - art_height - 18 - 49) // 23), left_width - 40

    def _sync_page(self) -> None:
        page = self.narrative.current
        token = (id(self.narrative), page.start, page.number, page.text) if page else None
        if token != self._page_token:
            self._page_token = token
            self._page_reveal = 0.0 if page and self.narrative.cinematic and self.ui.narration_delay and not self.ui.reduced_motion else float(len(page.text) if page else 0)
        if page:
            self.heading = page.heading
            self.scene_caption = page.scene_caption or "The road continues beneath the shadow."
            self._load_scene(page.scene_text, page.scene_caption)

    def _sync_world(self) -> None:
        self.world.set_request(self.request if not self.reading and not self.panels.active and not self.transcript_open else None)

    def _continue_reading(self) -> None:
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
        try:
            from .audio import AUDIO_DIRECTORY, SoundPlayer
            if self.pg.mixer.get_init() is None:
                self.pg.mixer.init()
            if cue not in self._sound_cache:
                filename = SoundPlayer.CUES.get(cue, SoundPlayer.CUES["notice"])
                self._sound_cache[cue] = self.pg.mixer.Sound(str(AUDIO_DIRECTORY / filename))
            self._sound_cache[cue].play()
        except (OSError, self.pg.error):
            pass

    def answer(self, answer: Any) -> None:
        if self.request is not None:
            if self.reading:
                return
            self._finish_narration()
            if self.request.story and isinstance(answer, str) and answer in dict(STORY_COMMANDS):
                self._saved_narrative = self.narrative
                self._saved_journey = self.hud.get("journey_id") if self.hud else None
                self.narrative = NarrativeDirector()
                self.narrative.scene_text = self._saved_narrative.scene_text
                self.narrative.scene_caption = self._saved_narrative.scene_caption
            if self.request.story and isinstance(answer, int) and 1 <= answer <= len(self.request.options):
                self.history.append(("> " + self.request.options[answer - 1], Color.CYAN, False))
                self.history_scroll = 0
            self.ui.submit(self.request, answer)
            self.request = None
            self.panels.close()
            self.world.set_request(None)
            self.choice_hits = []
            self.utility_hits = []
            self.pg.key.stop_text_input()

    def _toggle_fullscreen(self) -> None:
        if self.fullscreen:
            self.screen = self.pg.display.set_mode(self.window_size, self.pg.RESIZABLE)
        else:
            self.window_size = self.screen.get_size()
            self.screen = self.pg.display.set_mode((0, 0), self.pg.FULLSCREEN)
        self.fullscreen = not self.fullscreen

    def handle_event(self, event: Any) -> None:
        pg = self.pg
        if event.type == pg.QUIT:
            self.ui.close()
            return
        if event.type == pg.VIDEORESIZE and not self.fullscreen:
            self.window_size = (max(760, event.w), max(560, event.h))
            self.screen = pg.display.set_mode(self.window_size, pg.RESIZABLE)
            return
        if event.type == pg.KEYDOWN and event.key == pg.K_F11:
            self._toggle_fullscreen()
            return
        if self.panels.active:
            handled, action = self.panels.handle_event(event)
            if action is not None:
                self.answer(action)
            if handled:
                return
        if event.type == pg.KEYDOWN and event.key == pg.K_TAB:
            self._finish_narration()
            self.transcript_open = not self.transcript_open
            self._sync_world()
            self.history_scroll = 0
            return
        if event.type == pg.KEYDOWN and event.key in (pg.K_PAGEUP, pg.K_PAGEDOWN):
            self.world.set_request(None)
            self._finish_narration()
            self.transcript_open = True
            self.history_scroll = max(0, self.history_scroll + (8 if event.key == pg.K_PAGEUP else -8))
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
            handled, answer = self.world.handle_event(event)
            if answer is not None:
                self.soundscape.play_effect("interact")
                self.answer(answer)
            if handled:
                return
        if self._combat_active and self.request is not None and self.request.kind == "combat":
            handled, target = self.battle.handle_event(event)
            if target is not None:
                self.answer(CombatCommand("target", target))
            if handled:
                return
        if event.type == pg.MOUSEMOTION:
            hovered = next((answer - 1 for rect, answer in self.choice_hits if isinstance(answer, int) and rect.collidepoint(event.pos)), None)
            if hovered is not None and hovered != self.selected:
                self.selected = hovered
                self.soundscape.play_effect("hover")
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            for rect, answer in self.choice_hits + self.utility_hits:
                if rect.collidepoint(event.pos):
                    self._choose(answer) if isinstance(answer, int) else self.answer(answer)
                    return
        request = self.request
        if request is None:
            if self.finished and event.type == pg.KEYDOWN and event.key in (pg.K_RETURN, pg.K_ESCAPE):
                self.ui.close()
            return
        if request.kind == "text":
            if event.type == pg.TEXTINPUT:
                if self.entry_selected:
                    self.entry = ""
                    self.entry_selected = False
                self.entry += "".join(character for character in event.text if character.isprintable())[:64 - len(self.entry)]
            elif event.type == pg.KEYDOWN:
                if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                    self.answer(self.entry)
                elif event.key == pg.K_BACKSPACE:
                    self.entry = "" if self.entry_selected else self.entry[:-1]
                    self.entry_selected = False
                elif event.key == pg.K_a and getattr(event, "mod", 0) & pg.KMOD_CTRL:
                    self.entry_selected = True
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
        elif request.story and character in dict(STORY_COMMANDS) and not (self.world.active and character == "s"):
            self.answer(character)
        elif key == pg.K_ESCAPE and (request.story or request.allow_back):
            self.answer("m" if request.story else None)
        elif key in (pg.K_UP, pg.K_w, pg.K_k):
            self.selected = (self.selected - 1) % len(request.options)
            self._keep_selection_visible()
        elif key in (pg.K_DOWN, pg.K_s):
            self.selected = (self.selected + 1) % len(request.options)
            self._keep_selection_visible()
        elif key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE, pg.K_RIGHT, pg.K_d):
            self._choose(self.selected + 1)
        elif request.allow_back and key in (pg.K_LEFT, pg.K_a, pg.K_b):
            self.answer(None)
        elif character.isdigit() and character != "0" and int(character) <= len(request.options):
            self._choose(int(character))

    def _choose(self, answer: int) -> None:
        if self.request and self.request.kind == "combat" and self.battle.snapshot:
            actions = self.battle.snapshot.actions
            if 0 < answer <= len(actions) and not actions[answer - 1].enabled:
                self._toast(actions[answer - 1].disabled_reason or "That action is unavailable.")
                return
        self.answer(answer)

    def _choice_dimensions(self) -> list[tuple[int, list[str]]]:
        if self.request is None:
            return []
        width = max(70, self.menu_rect.width - 54)
        return [(max(50, len(lines) * 23 + 24), lines) for option in self.request.options for lines in [wrap_pixels(option, self.font, width)]]

    def _keep_selection_visible(self) -> None:
        dimensions = self._choice_dimensions()
        if not dimensions:
            return
        top = sum(height + 10 for height, _ in dimensions[:self.selected])
        bottom = top + dimensions[self.selected][0]
        viewport = max(1, self.menu_rect.height)
        if top < self.choice_scroll:
            self.choice_scroll = top
        elif bottom > self.choice_scroll + viewport:
            self.choice_scroll = bottom - viewport

    def _text(self, text: str, position: tuple[int, int], color: Any = PARCHMENT, font: Any = None) -> None:
        self.screen.blit((font or self.font).render(text, False, color), position)

    def _panel(self, rect: Any, color: Any = PANEL) -> None:
        self.pg.draw.rect(self.screen, color, rect)
        self.pg.draw.rect(self.screen, TEAL, rect, 1)
        for x, y in ((rect.left, rect.top), (rect.right - 5, rect.top), (rect.left, rect.bottom - 5), (rect.right - 5, rect.bottom - 5)):
            self.pg.draw.rect(self.screen, AMBER, (x, y, 5, 5))

    def render(self) -> None:
        pg = self.pg
        width, height = self.screen.get_size()
        now = pg.time.get_ticks()
        dt = min(0.25, max(0, now - self._frame_tick) / 1000)
        self._frame_tick = now
        self._advance_narration()
        if self._layout_size != (width, height):
            self._layout_size = (width, height)
            _, rows, text_width = self._reading_dimensions()
            self.narrative.repaginate(wrap=lambda text: wrap_pixels(text, self.font, text_width), rows=rows)
            self._sync_page()
            self._sync_world()
        if self.world.active and not self.panels.active and not self.transcript_open:
            before = self.world.player_position
            self.world.update(dt, reduced_motion=self.ui.reduced_motion)
            if self.world.player_position != before:
                self.soundscape.play_effect("footstep")
        self.battle.update(dt, reduced_motion=self.ui.reduced_motion)
        in_menu = self.request is not None and self.request.label == "MAIN MENU"
        audio_scene = None if in_menu else (self.world.map_key if self.world.active else (self.hud.get("scene") if self.hud else self.scene_key))
        self.soundscape.set_scene(audio_scene, combat=self._combat_active)
        self.soundscape.update(dt, enabled=self.ui.sound_enabled, music_volume=self.ui.music_volume, sfx_volume=self.ui.sfx_volume)
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
            self._text(f"{hud['name']}  |  Part {hud['chapter']}", (right_x, 19), PARCHMENT, self.small_font)
            self._text(f"HP {hud['hp']}/{hud['max_hp']}   FOCUS {hud['focus']}/{hud['max_focus']}", (right_x, 40), TEAL, self.small_font)
            meter_width = max(60, (right_width - 12) // 2)
            for x, value, maximum, color in ((right_x, hud['hp'], hud['max_hp'], AMBER), (right_x + meter_width + 12, hud['focus'], hud['max_focus'], TEAL)):
                pg.draw.rect(self.screen, PANEL, (x, 59, meter_width, 5))
                pg.draw.rect(self.screen, color, (x, 59, int(meter_width * max(0, min(1, value / max(1, maximum)))), 5))
            self._text(f"HOPE {hud['hope']}   SHADOW {hud['corruption']}", (right_x, 70), MUTED, self.small_font)
        top = 87
        available = height - top - 45
        art_height, _, _ = self._reading_dimensions()
        if self._combat_active and not self.reading:
            art_height = min(available - 130, max(art_height, 420))
        self.art_rect = pg.Rect(margin, top, left_width, art_height)
        self._panel(self.art_rect)
        inner = self.art_rect.inflate(-8, -8)
        if self.world.active and not self.reading:
            self.world.draw(self.screen, inner, now_ms=now, reduced_motion=self.ui.reduced_motion)
        elif self._combat_active and not self.reading and self.battle.snapshot is not None:
            self.battle.set_scene(self.scene)
            self.battle.draw(self.screen, inner, now)
        elif self.scene is not None:
            sw, sh = self.scene.get_size()
            # Integer enlargement at the default size; smaller windows still
            # use nearest-neighbor scaling to keep every edge crisp.
            scale = min(inner.width / sw, inner.height / sh)
            if scale >= 2:
                scale = int(scale)
            target = (max(1, int(sw * scale)), max(1, int(sh * scale)))
            picture = pg.transform.scale(self.scene, target)
            picture_rect = picture.get_rect(center=inner.center)
            self.screen.blit(picture, picture_rect)
            if self.ui.motion_enabled:
                self._ambient_pixels(picture_rect, scale)
        else:
            self._fallback_star(inner)
        self.history_rect = pg.Rect(margin, self.art_rect.bottom + gap, left_width, available - art_height - gap)
        self._panel(self.history_rect)
        self._render_history()
        right = pg.Rect(right_x, top, right_width, available)
        self._panel(right)
        label = self.heading if self.reading else (self.request.label if self.request is not None else ("JOURNEY COMPLETE" if self.finished else self.heading))
        label_lines = wrap_pixels(label.strip(), self.font, right.width - 32)
        label_y = right.top + 17
        for line in label_lines:
            self._text(line, (right.left + 16, label_y), AMBER)
            label_y += 23
        pg.draw.line(self.screen, TEAL, (right.left + 16, label_y + 7), (right.right - 16, label_y + 7))
        self.menu_rect = pg.Rect(right.left + 12, label_y + 22, right.width - 24, max(50, right.bottom - label_y - 44))
        self.choice_hits = []
        self.utility_hits = []
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
        if not self.reading and request is not None and request.kind in {"choice", "combat"}:
            self._render_choices()
        elif not self.reading and request is not None and request.kind == "text":
            field = pg.Rect(self.menu_rect.left + 4, self.menu_rect.top + 15, self.menu_rect.width - 8, 58)
            self._panel(field, (29, 43, 49) if self.entry_selected else INK)
            entry = self.entry
            while self.font.size(entry + "_")[0] > field.width - 22:
                entry = entry[1:]
            self._text(entry + "_", (field.left + 11, field.top + 19))
            self._render_continue("Begin the road", field.bottom + 21)
        elif not self.reading and request is not None and request.kind == "pause":
            self._render_continue("Continue", self.menu_rect.top + 12)
        elif self.finished:
            self._text("May a star shine", (self.menu_rect.left + 6, self.menu_rect.top + 22), TEAL)
            self._text("upon your road.", (self.menu_rect.left + 6, self.menu_rect.top + 47), TEAL)
            self._text("Return or Esc to close", (self.menu_rect.left + 6, self.menu_rect.top + 95), MUTED, self.small_font)
        footer = "WASD Walk   E Interact   1-9 Choose   F5 Save   TAB Transcript   F11 Fullscreen" if self.world.active else "ARROWS Select   RETURN Confirm   1-9 Choose   TAB Transcript   F11 Fullscreen"
        self._text(footer, (margin, height - 26), MUTED, self.small_font)
        if self.panels.active:
            shade = pg.Surface((width, height), pg.SRCALPHA)
            shade.fill((6, 10, 15, 205))
            self.screen.blit(shade, (0, 0))
            self.panels.draw(self.screen, pg.Rect(margin + 8, 75, width - margin * 2 - 16, height - 113))
        self._toasts[:] = [(text, expires) for text, expires in self._toasts if expires > now / 1000]
        for index, (text, _) in enumerate(reversed(self._toasts)):
            lines = wrap_pixels(text, self.small_font, min(520, width - 100))
            toast_width = max(self.small_font.size(line)[0] for line in lines) + 28
            toast = pg.Rect(width - toast_width - margin, height - 72 - index * 57 - max(0, len(lines) - 1) * 17, toast_width, 18 + len(lines) * 17)
            self._panel(toast, INK)
            for row, line in enumerate(lines):
                self._text(line, (toast.x + 13, toast.y + 8 + row * 17), AMBER, self.small_font)
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
        if not self.transcript_open and self._combat_active and not self.reading and self.battle.snapshot:
            self._text("BATTLE LOG  /  CLICK A FOE TO TARGET", (rect.left + 16, rect.top + 8), TEAL, self.small_font)
            snapshot = self.battle.snapshot
            entries = self._battle_log or [(snapshot.objective or "Read their intent before committing your move.", None, False)]
            lines = [(line, color) for text, color, _ in entries for line in wrap_pixels(text, self.font, rect.width - 40)]
            rows = max(1, (rect.height - 49) // 23)
            self.screen.set_clip(rect.inflate(-12, -12))
            for index, (line, color) in enumerate(lines[-rows:]):
                self._text(line, (rect.left + 16, rect.top + 29 + index * 23), TEAL if color == Color.GREEN else PARCHMENT)
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
                self._text(text, (rect.left + 16, rect.top + 29 + index * 23), color_map.get(line.color, PARCHMENT))
            self.screen.set_clip(None)
            if self.world.active:
                hint = self.world.inspection_text or self.world.hint_text
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
        rows = max(1, (rect.height - 40) // 23)
        maximum_scroll = max(0, len(self._text_layout) - rows)
        self.history_scroll = min(self.history_scroll, maximum_scroll)
        end = len(self._text_layout) - self.history_scroll
        start = max(0, end - rows)
        color_map = {Color.YELLOW: AMBER, Color.CYAN: TEAL, Color.GREEN: TEAL, Color.RED: RED, Color.MAGENTA: (171, 145, 195), Color.DIM: MUTED}
        self.screen.set_clip(rect.inflate(-12, -12))
        y = rect.top + 15
        for line, color, _bold in self._text_layout[start:end]:
            self._text(line, (rect.left + 16, y), color_map.get(color, PARCHMENT))
            y += 23
        self.screen.set_clip(None)
        if maximum_scroll:
            self._text(f"STORY  {end}/{len(self._text_layout)}", (rect.right - 145, rect.bottom - 18), TEAL, self.small_font)

    def _finish_narration(self) -> None:
        self._reveals.clear()
        self._history_layout_key = None
        self._page_reveal = float(len(self.narrative.current.text) if self.narrative.current else 0)

    def _advance_narration(self) -> None:
        now = self.pg.time.get_ticks()
        elapsed = max(0, now - self._last_tick) / 1000
        self._last_tick = now
        delay = self.ui.narration_delay
        if self.narrative.current and not self._page_finished:
            self._page_reveal = float(len(self.narrative.current.text)) if not delay or self.ui.reduced_motion else min(len(self.narrative.current.text), self._page_reveal + elapsed * (5.0 / delay))
            if self._page_finished:
                self._sync_world()

    def _render_choices(self) -> None:
        dimensions = self._choice_dimensions()
        total = sum(height + 10 for height, _ in dimensions) - 10
        self.choice_scroll = min(self.choice_scroll, max(0, total - self.menu_rect.height))
        self.screen.set_clip(self.menu_rect)
        y = self.menu_rect.top - self.choice_scroll
        for index, (height, lines) in enumerate(dimensions):
            rect = self.pg.Rect(self.menu_rect.left + 3, y, self.menu_rect.width - 6, height)
            selected = index == self.selected
            action = self.battle.snapshot.actions[index] if self.request and self.request.kind == "combat" and self.battle.snapshot and index < len(self.battle.snapshot.actions) else None
            enabled = action is None or action.enabled
            self._panel(rect, (39, 49, 50) if selected else INK)
            if selected:
                self.pg.draw.rect(self.screen, AMBER, (rect.left, rect.top, 4, rect.height))
            self._text(str(index + 1).zfill(2), (rect.left + 12, rect.top + 13), AMBER if selected else TEAL, self.small_font)
            for line_number, line in enumerate(lines):
                self._text(line, (rect.left + 39, rect.top + 12 + line_number * 23), PARCHMENT if enabled else MUTED)
            clipped = rect.clip(self.menu_rect)
            if clipped.height > 0:
                self.choice_hits.append((clipped, index + 1))
            y += height + 10
        self.screen.set_clip(None)
        if total > self.menu_rect.height:
            self._text("Scroll or use arrows for more", (self.menu_rect.left + 5, self.menu_rect.bottom + 4), TEAL, self.small_font)

    def _render_utilities(self, right: Any) -> None:
        button_width = (right.width - 42) // 2
        for index, (command, label) in enumerate(STORY_COMMANDS):
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


def launch_pixel_game(game: Any, ui: PixelUI, *, screenshot: Path | None = None) -> None:
    """Run the unchanged Game with a responsive graphical display."""
    window = PixelWindow(ui)
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
            if screenshot is not None and window.request is not None:
                screenshot_frames += 1
                if screenshot_frames >= 2:
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    window.pg.image.save(window.screen, str(screenshot))
                    ui.close()
            window.clock.tick(60)
    finally:
        ui.close()
        worker.join(timeout=1.0)
        window.pg.quit()
