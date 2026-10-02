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
