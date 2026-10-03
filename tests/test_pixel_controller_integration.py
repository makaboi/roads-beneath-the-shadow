"""Mapped physical-state events reach real SDL windows and ordinary UI workers.

The fake device supplies hardware state and SDL identity only. pygame constants,
events, rendering, GamepadInput, and PixelWindow dispatch are real; no PadAction
is dispatched directly and no global pygame joystick backend is patched.
"""

from __future__ import annotations

from dataclasses import replace
import gc
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat_view import CombatActionView, CombatCommand, CombatFeedback
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.controller_input import GamepadInput
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_ui import InputRequest, PixelUI, PixelWindow, UIEvent
from roads_beneath_shadow.profile import ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import UserSettings
from roads_beneath_shadow.ui import InputClosed
from tests import test_controller_input as physical_fixtures
from tests import test_pixel_battle as battle_fixtures
from tests import test_pixel_world as world_fixtures


class DevicePygame:
    """Use pygame's real event enums and only replace device identity lookup."""

    def __init__(self, pg, backend):
        self._pg = pg
        self.joystick = SimpleNamespace(Joystick=backend.Joystick)

    def __getattr__(self, name):
        return getattr(self._pg, name)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for SDL controller integration")
class ControllerWindowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.ui = PixelUI(fast=True, text_speed="instant", sound=False)
        self.window = PixelWindow(self.ui, size=(760, 560))
        self.pg = self.window.pg
        self.window.gamepad.close()
        self.device = physical_fixtures.FakeController(903, name="Mapped integration controller")
        self.backend = physical_fixtures.FakeBackend([self.device])
        self.window.gamepad = GamepadInput(DevicePygame(self.pg, self.backend), self.backend)
        self.workers = []
        self.errors = []
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.ui.close()
        for worker in self.workers:
            worker.join(2)
            self.assertFalse(worker.is_alive(), "an owned UI worker did not finish")
        self.window.gamepad.close()
        self.assertEqual(self.device.quit_calls, 1)
        self.assertEqual(self.backend.quit_calls, 1)
        self.assertEqual(self.errors, [])
        self.window = None
        gc.collect()
        self.pg.quit()
        self.temp.cleanup()

    def frame(self, dt=0.05):
        self.window.drain()
        self.window._frame_tick = self.pg.time.get_ticks() - round(dt * 1000)
        self.window.render()
        self.assertIsNone(self.window.error)

    def button(self, name, down=True, *, device=None):
        device = device or self.device
        code = getattr(self.pg, "CONTROLLER_BUTTON_" + name)
        if down:
            device.buttons.add(code)
        else:
            device.buttons.discard(code)
        event = self.pg.event.Event(self.pg.CONTROLLERBUTTONDOWN if down else self.pg.CONTROLLERBUTTONUP,
                                   instance_id=device.instance_id, button=code)
        self.window.handle_event(event)

    def tap(self, name):
        self.button(name)
        self.frame()
        self.button(name, False)
        self.frame()

    def axis(self, value, axis="LEFTX"):
        code = getattr(self.pg, "CONTROLLER_AXIS_" + axis)
        self.device.axes[code] = value
        self.window.handle_event(self.pg.event.Event(self.pg.CONTROLLERAXISMOTION,
                                                     instance_id=self.device.instance_id, axis=code, value=value))

    def publish(self, request, *, snapshot=None):
        if snapshot is not None:
            self.ui.events.put(UIEvent("combat_snapshot", {"snapshot": snapshot}))
        self.ui.events.put(UIEvent("request", {"request": request, "hud": None}))
        self.frame()

    def menu(self, identifier=1, *, kind="choice", allow_back=True):
        request = InputRequest(identifier, kind, "Choose your route", ("First route", "Second route", "Third route"), allow_back)
        self.publish(request)
        return request

    def world(self):
        fixture = world_fixtures.request_for("bree")
        request = InputRequest(1, "choice", fixture.label, fixture.options, story=True,
                               context={"origin": "north_road_scout"})
        self.publish(request)
        self.assertTrue(self.window.world.active)
        return request

    def start_worker(self, callback):
        def run():
            try:
                callback()
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)
        worker = threading.Thread(target=run)
        self.workers.append(worker)
        worker.start()
        return worker

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.frame()
            self.assertEqual(self.errors, [])
            if predicate():
                return
            time.sleep(0.001)
        self.fail("the ordinary UI worker did not reach the expected request")

    def game(self):
        root = Path(self.temp.name)
        return Game(self.ui, saves=SaveManager(root / "saves"), profile=ProfileManager(root / "profile.json"),
                    user_settings=UserSettings(text_speed="instant", sound=False))

    def test_real_controller_dpad_selects_and_a_confirms_the_menu(self):
        request = self.menu()
        self.tap("DPAD_DOWN")
        self.assertEqual(self.window.selected, 1)
        self.assertIs(self.window.request, request)
        self.assertTrue(self.ui.responses.empty())
        self.tap("A")
        self.assertEqual(self.ui.responses.get_nowait(), (request.identifier, 2))

    def test_horizontal_repeat_and_left_stick_never_confirm_a_menu_or_paid_combat_action(self):
        snapshot = battle_fixtures.battle_snapshot()
        for kind in ("choice", "combat"):
            request = InputRequest(1, kind, "Choose your action", tuple(action.label for action in snapshot.actions))
            self.publish(request, snapshot=snapshot if kind == "combat" else None)
            for direction in ("DPAD_LEFT", "DPAD_RIGHT"):
                self.button(direction)
                for _ in range(8):
                    self.frame(0.25)
                self.button(direction, False)
                self.frame()
            self.axis(32767)
            for _ in range(8):
                self.frame(0.25)
            self.axis(0)
            self.frame()
            self.assertIs(self.window.request, request)
            self.assertTrue(self.ui.responses.empty())
            self.assertEqual(self.window.selected, 0)

    def test_a_requires_a_new_edge_and_neutral_between_successive_requests(self):
        first = self.menu()
        self.button("A")
        self.assertEqual(self.ui.responses.get_nowait(), (first.identifier, 1))
        second = self.menu(2)
        self.button("A")  # Duplicate while still physically held.
        for _ in range(6):
            self.frame(0.25)
        self.assertIs(self.window.request, second)
        self.assertTrue(self.ui.responses.empty())
        self.button("A", False)
        self.frame()
        self.tap("A")
        self.assertEqual(self.ui.responses.get_nowait(), (second.identifier, 1))

    def test_keyboardless_name_keyboard_done_and_background_creation_use_real_controller_events(self):
        game = self.game()
        self.ui.state_provider = lambda: game.state
        result = []
        worker = self.start_worker(lambda: result.append(game._new_journey()))
        self.wait_for(lambda: self.window.request is not None and self.window.request.kind == "text")
        self.tap("X")
        self.assertTrue(self.window.name_keyboard.active)
        self.tap("A")  # The first real keyboard tile is q.
        self.assertEqual(self.window.entry, "q")
        for _ in range(4):
            self.tap("DPAD_DOWN")
        for _ in range(3):
            self.tap("DPAD_RIGHT")
        self.assertEqual(self.window.name_keyboard.selected_key, "done")
        self.tap("A")
        self.wait_for(lambda: self.window.panels.active and self.window.panels.kind == "background")
        self.tap("DPAD_RIGHT")
        self.tap("A")
        self.wait_for(lambda: self.window.request is not None and self.window.request.label == "Accept this background?")
        self.tap("A")
        self.wait_for(lambda: self.window.request is not None and self.window.request.label == "What lesson from Calenor do you carry?")
        self.tap("DPAD_DOWN")
        self.tap("A")
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertEqual(game.state.character.name, "q")
        self.assertEqual(game.state.character.origin, "north_road_scout")
        self.assertTrue(game.state.flags["lesson_tracking"])

    def test_b_closes_the_name_keyboard_first_then_cancels_creation(self):
        game = self.game()
        self.ui.state_provider = lambda: game.state
        result = []
        worker = self.start_worker(lambda: result.append(game._new_journey()))
        self.wait_for(lambda: self.window.request is not None and self.window.request.kind == "text")
        name_request = self.window.request
        self.tap("X")
        self.tap("A")
        self.tap("B")
        self.assertFalse(self.window.name_keyboard.active)
        self.assertIs(self.window.request, name_request)
        self.assertEqual(self.window.entry, "q")
        self.assertTrue(worker.is_alive())
        self.tap("B")
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])
        self.assertIsNone(game.state)

    def test_world_dpad_navigates_choices_without_moving_the_hero(self):
        request = self.world()
        before = self.window.world.player_position
        self.button("DPAD_DOWN")
        for _ in range(12):
            self.frame(0.1)
        self.button("DPAD_DOWN", False)
        self.frame()
        self.assertEqual(self.window.world.player_position, before)
        self.assertEqual(self.window.gamepad.movement, (0.0, 0.0))
        self.assertTrue(self.window._menu_focused)
        self.assertIs(self.window.request, request)
        self.assertTrue(self.ui.responses.empty())

    def test_fractional_world_stick_moves_and_focus_loss_requires_neutral_before_resuming(self):
        self.world()
        before = self.window.world.player_position
        self.axis(round(0.5 * 32767))
        self.frame()
        self.assertAlmostEqual(self.window.gamepad.movement[0], 0.375, places=4)
        moved = self.window.world.player_position
        self.assertGreater(moved[0], before[0])
        self.assertEqual(moved[1], before[1])
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        for _ in range(4):
            self.frame()
        self.assertEqual(self.window.world.player_position, moved)
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSGAINED))
        self.frame()
        self.assertEqual(self.window.world.player_position, moved)
        self.axis(0)
        self.frame()
        self.axis(round(0.5 * 32767))
        self.frame()
        self.assertGreater(self.window.world.player_position[0], moved[0])

    def test_archive_modal_stops_a_held_stick_until_it_returns_to_neutral(self):
        self.world()
        self.axis(round(0.5 * 32767))
        self.frame()
        stopped = self.window.world.player_position
        self.tap("BACK")
        self.assertTrue(self.window.transcript_open)
        for _ in range(5):
            self.frame()
        self.assertEqual(self.window.world.player_position, stopped)
        self.tap("B")
        self.assertTrue(self.window.transcript_open, "a held stick must remain gated in the modal")
        self.axis(0)
        self.frame()
        self.tap("B")
        self.assertFalse(self.window.transcript_open)
        self.frame()
        self.assertEqual(self.window.world.player_position, stopped)
        self.axis(round(0.5 * 32767))
        self.frame()
        self.assertGreater(self.window.world.player_position[0], stopped[0])

    def test_hotplug_removal_stops_movement_and_gates_the_replacement_held_stick(self):
        self.world()
        self.axis(round(0.5 * 32767))
        self.frame()
        stopped = self.window.world.player_position
        replacement = physical_fixtures.FakeController(44)
        replacement.axes[0] = 32767
        self.backend.devices.append(replacement)
        self.window.handle_event(self.pg.event.Event(self.pg.CONTROLLERDEVICEADDED, device_index=1))
        self.backend.detach(self.device.instance_id)
        self.window.handle_event(self.pg.event.Event(self.pg.CONTROLLERDEVICEREMOVED,
                                                     instance_id=self.device.instance_id))
        self.frame()
        self.assertEqual(self.window.gamepad.active_instance_id, 44)
        self.assertEqual(self.window.world.player_position, stopped)
        replacement.axes[0] = 0
        self.frame()
        replacement.axes[0] = round(0.5 * 32767)
        self.frame()
        self.assertGreater(self.window.world.player_position[0], stopped[0])
        self.window.gamepad.close()
        self.assertEqual(replacement.quit_calls, 1)

    def test_all_story_utilities_restore_the_same_complete_player_state_and_live_choices(self):
        game = self.game()
        game.state = GameState(Character.from_origin("éowen Controller", ORIGINS[1]), scene="bree_exploration")
        game.state.add_journal("A controller integration fixture observes the story without changing it.")
        self.ui.state_provider = lambda: game.state
        expected = game.state.to_dict()
        fixture = world_fixtures.request_for("bree")
        result = []
        worker = self.start_worker(lambda: result.append(game._story_choice(fixture.label, fixture.options)))
        self.wait_for(lambda: self.window.request is not None and self.window.request.story)
        for button, kind in (("X", "inventory"), ("Y", "journal"), ("LEFTSTICK", "map"),
                             ("RIGHTSTICK", "character"), ("START", "pause"), ("BACK", "archive")):
            with self.subTest(utility=kind):
                self.tap(button)
                if kind == "pause":
                    self.wait_for(lambda: self.window.request is not None and self.window.request.label == "JOURNEY PAUSED")
                elif kind == "archive":
                    self.assertTrue(self.window.transcript_open)
                else:
                    self.wait_for(lambda: self.window.panels.active)
                    self.assertEqual(self.window.panels.kind, kind)
                self.tap("B")
                self.wait_for(lambda: self.window.request is not None and self.window.request.story
                              and not self.window.panels.active and not self.window.transcript_open)
                self.assertEqual(self.window.request.options, fixture.options)
                self.assertEqual(game.state.to_dict(), expected)
        self.tap("DPAD_DOWN")
        self.tap("A")
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [2])
        self.assertEqual(game.state.to_dict(), expected)

    def test_combat_x_inspection_and_shoulders_are_free_while_paid_a_waits_for_the_impact(self):
        snapshot = battle_fixtures.battle_snapshot()
        snapshot = replace(snapshot, actions=(*snapshot.actions, CombatActionView("inspect", "Inspect", 0, True, "", "Read freely.")))
        request = InputRequest(1, "combat", "Choose your action", tuple(action.label for action in snapshot.actions))
        self.publish(request, snapshot=snapshot)
        self.ui.events.put(UIEvent("combat_feedback", {"feedback": CombatFeedback("damage", "player", "enemy_0", 4, "A strike lands.")}))
        self.window.drain()
        self.assertTrue(self.window.battle.busy)
        self.tap("A")
        self.assertTrue(self.ui.responses.empty())
        self.tap("X")
        self.assertEqual(self.ui.responses.get_nowait(), (1, len(snapshot.actions)))
        self.publish(replace(request, identifier=2), snapshot=snapshot)
        self.tap("RIGHTSHOULDER")
        self.assertEqual(self.ui.responses.get_nowait(), (2, CombatCommand("target", "enemy_1")))
        self.publish(replace(request, identifier=3), snapshot=replace(snapshot, target_id="enemy_1"))
        self.tap("LEFTSHOULDER")
        self.assertEqual(self.ui.responses.get_nowait(), (3, CombatCommand("target", "enemy_0")))
        self.publish(replace(request, identifier=4), snapshot=snapshot)
        for _ in range(20):
            self.frame(0.1)
        self.assertFalse(self.window.battle.busy)
        self.tap("A")
        self.assertEqual(self.ui.responses.get_nowait(), (4, 1))


if __name__ == "__main__":
    unittest.main()
