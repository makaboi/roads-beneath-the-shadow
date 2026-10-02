"""Player input cannot skip an impact or answer while local help is open."""

from dataclasses import replace
import importlib.util
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from roads_beneath_shadow.combat_view import CombatActionView, CombatCommand, CombatFeedback
from roads_beneath_shadow.pixel_ui import InputRequest, PixelUI, PixelWindow, UIEvent
from tests.test_pixel_battle import battle_snapshot


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for desktop controls")
class BattleLocationPreludeTests(unittest.TestCase):
    def check_actual_prelude(self, opening, subject, choices=None, *, scene="final_battle", backdrop=None, flags=None,
                             size=(1200, 900), text_size="standard", fullscreen=False, check_bridge_footing=False):
        import random
        import tempfile
        import threading
        import time
        from pathlib import Path
        from roads_beneath_shadow.app import Game
        from roads_beneath_shadow.content import ORIGINS
        from roads_beneath_shadow.models import Character, GameState
        from roads_beneath_shadow.pixel_art import ASSET_DIR
        from roads_beneath_shadow.profile import ProfileManager
        from roads_beneath_shadow.savegame import SaveManager
        from roads_beneath_shadow.settings import SettingsManager, UserSettings
        from roads_beneath_shadow.ui import InputClosed

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ui = PixelUI(text_speed="instant", sound=False)
            window = PixelWindow(ui, size=size)
            pg = window.pg
            game = Game(ui, rng=random.Random(59), saves=SaveManager(directory / "saves"), profile=ProfileManager(directory / "profile.json"), settings_manager=SettingsManager(directory / "settings.json"), user_settings=UserSettings(text_speed="instant", sound=False, text_size=text_size))
            game.state = GameState(
                Character.from_origin("Mira", ORIGINS[2]),
                scene="chapter1_intro" if opening else scene,
                chapter=2 if scene.startswith("part2_") else 1,
                flags=dict(flags or {}),
            )
            ui.state_provider = lambda: game.state
            errors = []

            def source_worker():
                try:
                    if opening:
                        game._chapter_one_intro()
                        if game._chapter_one_decision():
                            getattr(game, "_" + game.state.scene)()
                    elif scene.startswith("part2_"):
                        game.part_two.run_scene(game.state)
                    else:
                        getattr(game, "_" + scene)()
                except InputClosed:
                    pass
                except Exception as error:
                    errors.append(error)

            worker = threading.Thread(target=source_worker)
            worker.start()

            def key(code):
                text = chr(code) if 32 <= code < 127 else "\r" if code == pg.K_RETURN else ""
                window.handle_event(pg.event.Event(pg.KEYDOWN, key=code, unicode=text, mod=0))

            try:
                if fullscreen:
                    key(pg.K_F11)
                    self.assertTrue(window.fullscreen)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    window.drain()
                    window.render()
                    self.assertEqual(errors, [])
                    self.assertIsNone(window.error)
                    request = window.request
                    if window.reading:
                        key(pg.K_RETURN)
                    elif request and request.kind == "combat":
                        break
                    elif request and request.kind == "pause":
                        key(pg.K_RETURN)
                    elif request and request.story:
                        answer = opening if request.label == "WHAT WILL YOU DO?" else (choices or {}).get(request.label)
                        self.assertIsNotNone(answer, f"Unexpected source choice: {request.label}")
                        key(pg.K_1 + answer - 1)
                    time.sleep(0.001)
                else:
                    self.fail("The actual story prelude did not reach combat")

                expected = backdrop or ("tavern-interior" if opening else subject)
                expected_image = pg.image.load(str(ASSET_DIR / f"{expected}.png")).convert()
                self.assertEqual(window.scene_key, subject, "the prose illustration changed")
                self.assertEqual(pg.image.tobytes(window.battle._scene_override, "RGB"), pg.image.tobytes(expected_image, "RGB"))
                if check_bridge_footing:
                    crop = window.battle.backdrop_crop
                    self.assertIsNotNone(crop)
                    scaled_image = window.battle._scaled_backdrop[2]
                    scale_y = scaled_image.get_height() / expected_image.get_height()
                    # The authored bridge's stone deck occupies native rows
                    # 125–155; inspect the actual blit crop and actor anchors.
                    for actor, position in window.battle.actor_positions.items():
                        foot_y = (crop.y + position[1] - window.battle._arena_rect.y) / scale_y
                        self.assertGreaterEqual(foot_y, 125, (actor, foot_y, size, text_size))
                        self.assertLessEqual(foot_y, 155, (actor, foot_y, size, text_size))
                if not opening and not backdrop:
                    self.assertIs(window.battle._scene_override, window.scene)
                state_before = game.state.to_dict()
                options = request.options
                portrait = window.scene
                cache_size = len(window.scene_cache)
                for _ in range(4):
                    window.render()
                self.assertIs(window.scene, portrait)
                self.assertEqual(len(window.scene_cache), cache_size)
                self.assertIs(window.request, request)
                self.assertEqual(request.options, options)
                self.assertEqual(game.state.to_dict(), state_before)
                self.assertTrue(ui.responses.empty())
            finally:
                ui.close()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                pg.quit()
                self.assertEqual(errors, [])

    def test_pony_fights_keep_the_room_and_preserve_each_actual_subject_prelude(self):
        for opening, subject, choices in (
            (1, "orc", {}),
            (2, "broken-key", {}),
            (3, "map", {}),
            (4, "tavern-interior", {"IN THE KITCHEN": 1}),
            (5, "orc", {"PRESS YOUR QUESTION": 1}),
        ):
            with self.subTest(opening=opening):
                self.check_actual_prelude(opening, subject, choices)

    def test_non_pony_battle_keeps_the_actual_ghorak_prelude_backdrop(self):
        self.check_actual_prelude(None, "ghorak", {"THE FINAL BATTLE": 1})

    def test_seal_door_and_last_seal_fights_keep_their_indoor_locations(self):
        for scene, subject, choices in (
            ("part2_teren", "ranger", {"HOW DO YOU ANSWER TEREN?": 1, "IF TEREN YIELDS, WHAT FATE WILL FOLLOW?": 1}),
            ("part2_final_battle", "rider", {"WHERE DO YOU STAND FOR SIX ROUNDS?": 1}),
        ):
            for present in (False, True):
                with self.subTest(scene=scene, companions=present):
                    self.check_actual_prelude(None, subject, choices, scene=scene, backdrop="seal", flags={
                        "part_two_mara_present": present,
                        "part_two_tobin_present": present,
                    })

    def test_other_actual_combat_preludes_keep_their_existing_locations(self):
        for scene, subject, choices in (
            ("marsh_ambush", "orc", {}),
            ("part2_pursuit", "seal", {"HOW DO YOU BUY FOUR ROUNDS?": 1}),
            ("part2_chain_troll", "troll", {"THE CHAINS ARE ARMOR AND LEASH": 1, "WHAT BECOMES OF THE DROWNED MILE?": 1}),
        ):
            with self.subTest(scene=scene):
                self.check_actual_prelude(None, subject, choices, scene=scene)

    def test_echo_bridge_uses_its_gulf_backdrop_for_both_live_approaches_and_party_sizes(self):
        for present in (False, True):
            for approach, subject in ((1, "orc"), (2, "seal")):
                with self.subTest(companions=present, approach=approach):
                    self.check_actual_prelude(None, subject, {
                        "HOW DO YOU REACH ECHO BRIDGE?": approach,
                        "WHAT MUST SURVIVE AT ECHO BRIDGE?": 1,
                    }, scene="part2_echo_bridge", backdrop="echo-bridge-battle", flags={
                        "part_two_mara_present": present,
                        "part_two_tobin_present": present,
                        "part_two_hidden_route_known": True,
                    })

    def test_actual_bridge_footing_survives_minimum_large_reading_and_fullscreen_frames(self):
        choices = {"HOW DO YOU REACH ECHO BRIDGE?": 1, "WHAT MUST SURVIVE AT ECHO BRIDGE?": 1}
        flags = {"part_two_mara_present": True, "part_two_tobin_present": True}
        for size in ((760, 560), (1200, 900), (1920, 1080)):
            for text_size in ("standard", "larger"):
                with self.subTest(size=size, text_size=text_size):
                    self.check_actual_prelude(None, "orc", choices, scene="part2_echo_bridge", backdrop="echo-bridge-battle",
                                              flags=flags, size=size, text_size=text_size, check_bridge_footing=True)
        self.check_actual_prelude(None, "orc", choices, scene="part2_echo_bridge", backdrop="echo-bridge-battle",
                                  flags=flags, size=(760, 560), text_size="larger", fullscreen=True, check_bridge_footing=True)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for desktop controls")
class CombatControlsTests(unittest.TestCase):
    def setUp(self):
        self.ui = PixelUI(text_speed="instant")
        self.window = PixelWindow(self.ui, size=(760, 560))
        self.pg = self.window.pg
        snapshot = battle_snapshot()
        self.snapshot = replace(snapshot, actions=(*snapshot.actions,
            CombatActionView("inspect", "Inspect", 0, True, "", "Read the enemy without using your turn.")))
        self.request = InputRequest(1, "combat", "Choose your action", tuple(action.label for action in self.snapshot.actions))
        self.ui.events.put(UIEvent("combat_snapshot", {"snapshot": self.snapshot}))
        self.ui.events.put(UIEvent("request", {"request": self.request, "hud": None}))
        self.window.drain()
        self.window.render()

    def tearDown(self):
        self.ui.close()
        self.pg.quit()

    def key(self, key, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=0))

    def queue_hit(self):
        self.ui.events.put(UIEvent("combat_feedback", {"feedback": CombatFeedback("damage", "player", "enemy_0", 4, "Mira hits the captain.")}))
        self.window.drain()

    def test_paid_action_waits_for_impact_then_accepts_the_same_key(self):
        self.queue_hit()
        self.key(self.pg.K_1, "1")
        self.assertIs(self.window.request, self.request)
        self.assertTrue(self.ui.responses.empty())
        self.window.battle.update(0.8)
        self.key(self.pg.K_1, "1")
        self.assertEqual(self.ui.responses.get_nowait(), (1, 1))

    def test_targeting_and_inspection_remain_free_while_impact_is_pending(self):
        self.queue_hit()
        self.key(self.pg.K_RIGHTBRACKET, "]")
        self.assertEqual(self.ui.responses.get_nowait(), (1, CombatCommand("target", "enemy_1")))
        self.window.request = self.request
        self.key(self.pg.K_5, "5")
        self.assertEqual(self.ui.responses.get_nowait(), (1, 5))
        self.assertEqual(self.window.battle.snapshot.round_number, self.snapshot.round_number)

    def test_final_hit_stays_on_screen_until_the_story_transition(self):
        self.queue_hit()
        final = replace(self.snapshot, phase="victory", enemies=tuple(replace(enemy, hp=0) for enemy in self.snapshot.enemies))
        self.ui.events.put(UIEvent("combat_snapshot", {"snapshot": final}))
        self.ui.events.put(UIEvent("clear"))
        self.ui.events.put(UIEvent("text", {"text": "The road opens.", "narration": True}))
        next_request = InputRequest(2, "choice", "Where next?", ("Follow the road",), story=True)
        self.ui.events.put(UIEvent("request", {"request": next_request, "hud": None}))
        self.window.drain()
        self.window.render()
        self.assertTrue(self.window._combat_active)
        self.assertIs(self.window.battle.snapshot, final)
        self.assertFalse(any(text == "The road opens." for text, _, _ in self.window.history))
        self.window.battle.update(0.8)
        self.window.drain()
        self.assertIs(self.window.request, next_request)
        self.assertFalse(self.window._combat_active)
        self.assertIn("The road opens.", self.window.narrative.current.text)

    def test_help_closes_to_the_same_selected_action_without_answering(self):
        self.key(self.pg.K_DOWN)
        self.key(self.pg.K_F1)
        self.key(self.pg.K_1, "1")
        self.key(self.pg.K_ESCAPE)
        self.assertIs(self.window.request, self.request)
        self.assertEqual(self.window.selected, 1)
        self.assertFalse(self.window.panels.active)
        self.assertTrue(self.ui.responses.empty())

    def test_header_health_waits_for_the_visible_incoming_impact(self):
        updated = replace(self.snapshot, player=replace(self.snapshot.player, hp=14))
        hud = {"name": "Mira", "chapter": 1, "hp": 14, "max_hp": 24,
               "focus": 3, "max_focus": 4, "hope": 0, "corruption": 0}
        self.ui.events.put(UIEvent("combat_feedback", {"feedback":
            CombatFeedback("damage", "enemy_1", "player", 3, "The archer hits.")}))
        self.ui.events.put(UIEvent("combat_snapshot", {"snapshot": updated}))
        self.ui.events.put(UIEvent("request", {"request": replace(self.request, identifier=2), "hud": hud}))
        self.window.drain()
        visible = []
        draw = self.window._text

        def record(text, position, *args):
            if position[1] == 40:
                visible.append(text)
            draw(text, position, *args)

        self.window._text = record
        tick = self.pg.time.get_ticks()
        self.window._frame_tick = tick
        with patch.object(self.pg.time, "get_ticks", return_value=tick):
            self.window.render()
            self.assertIn("HP 17/24   FOCUS 3/4", visible)
            self.window.battle.update(0.19)
            self.window.render()
            self.assertEqual(visible[-1], "HP 14/24   FOCUS 3/4")
        self.assertEqual(updated.player.hp, 14)
        self.assertEqual(hud["hp"], 14)

    def test_compact_log_keeps_paid_mara_impact_and_incoming_damage_visible(self):
        snapshot = replace(self.snapshot, actions=(*self.snapshot.actions,
            CombatActionView("mara", "Mara: Crossing Blades (-1 Focus)", 1, True, "", "Strike and interrupt.")))
        request = replace(self.request, options=tuple(action.label for action in snapshot.actions))
        self.window.request = request
        self.window.battle.set_snapshot(snapshot)
        self.window._choose(len(snapshot.actions))
        self.assertEqual(self.ui.responses.get_nowait(), (1, len(snapshot.actions)))
        for feedback in (
            CombatFeedback("damage", "mara", "enemy_0", 8, "Mara strikes."),
            CombatFeedback("interrupt", "mara", "enemy_0", 0, "The captain's blow is interrupted."),
            CombatFeedback("damage", "enemy_1", "player", 3, "The archer hits."),
            CombatFeedback("damage", "player", "player", 1, "Bleeding costs 1 Health."),
        ):
            self.ui.events.put(UIEvent("combat_feedback", {"feedback": feedback}))
        self.ui.events.put(UIEvent("request", {"request": replace(request, identifier=2), "hud": None}))
        self.window.drain()
        visible = []
        draw = self.window._text

        def record(text, position, *args):
            if self.window.history_rect.collidepoint(position):
                visible.append(text)
            draw(text, position, *args)

        self.window._text = record
        self.window.render()
        self.assertTrue(any("Mara" in line and "8" in line and "interrupt" in line for line in visible), visible)
        self.assertTrue(any("3 Health" in line and "Bleeding" in line and "1" in line for line in visible), visible)
