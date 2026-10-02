"""Real SDL coverage for the battlefield's interactions and motion settings."""

from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.combat_view import (
    CombatActionView, CombatCompanionView, CombatEnemyView, CombatFeedback, CombatPlayerView,
    CombatSnapshot, CombatStatusView,
)
from roads_beneath_shadow.pixel_battle import BattleView, _wrapped


def battle_snapshot(count=3):
    bleeding = CombatStatusView("bleeding", "Bleeding", 2, "Lose 1 Health at the start of each turn.")
    player = CombatPlayerView("Mira", "North Road Scout", 17, 24, 3, 4, "sword", "Ranger's sword", "leather", "Leather coat", 1, (bleeding,))
    names = ("Orc Captain", "Ash-Hand Sapper", "Ash-Hand Archer")
    archetypes = ("commander", "saboteur", "archer")
    enemies = tuple(
        CombatEnemyView(f"enemy_{index}", names[index], archetypes[index], 12 - index * 3, 16 - index * 3, 1 if index == 0 else 0, 1,
                        "heavy", "Heavy Blow", "a crushing attack; Defend or interrupt it", True, 4, 8, "4–8 incoming damage", (), index == 0)
        for index in range(count)
    )
    actions = (CombatActionView("attack", "Attack", 0, True, "", "Strike the target."),
               CombatActionView("power", "Power Attack", 1, True, "", "Disrupt the target."),
               CombatActionView("defend", "Defend", 0, True, "", "Halve incoming weapon damage."),
               CombatActionView("mara", "Mara: Crossing Blades", 1, True, "", "Disrupt the target."))
    return CombatSnapshot(2, "active", "Ranger", player, enemies, "enemy_0", actions,
                          (CombatCompanionView("mara", "Mara", 3, True), CombatCompanionView("tobin", "Tobin", 2, True)),
                          "Protect the prisoners and keep the bridge intact.", None, False)


class BattleImportTests(unittest.TestCase):
    def test_import_is_safe_without_a_graphical_display(self):
        code = "import sys; import roads_beneath_shadow.pixel_battle; assert 'pygame' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is required for battlefield SDL tests")
class BattleSDLTests(unittest.TestCase):
    def setUp(self):
        import pygame
        self.pg = pygame
        pygame.init()
        self.surface = pygame.Surface((1000, 760))
        self.view = BattleView(pygame)
        self.snapshot = battle_snapshot()
        self.view.set_snapshot(self.snapshot)
        self.canvas = pygame.Rect(24, 100, 620, 480)
        self.view.draw(self.surface, self.canvas, 400)

    def tearDown(self):
        self.pg.quit()

    def click(self, pos, button=1):
        return self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=button, pos=pos))

    def test_selecting_enemy_cards_returns_stable_engine_ids(self):
        for rect, enemy_id in self.view.enemy_hits:
            self.assertEqual(self.click(rect.center), (True, enemy_id))
        self.assertEqual(self.snapshot.target_id, "enemy_0", "the renderer must leave selection to the engine")

    def test_selecting_the_visible_enemy_sprite_returns_the_same_target(self):
        for rect, enemy_id in self.view.sprite_hits:
            self.assertEqual(self.click(rect.center), (True, enemy_id))

    def test_fallen_enemy_stays_visible_but_cannot_be_targeted(self):
        enemies = (replace(self.snapshot.enemies[0], hp=0), *self.snapshot.enemies[1:])
        self.view.set_snapshot(replace(self.snapshot, enemies=enemies, target_id="enemy_1"))
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(len(self.view.enemy_hits), 3)
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center), (True, None))
        self.assertEqual(self.click(self.view.enemy_hits[1][0].center), (True, "enemy_1"))

    def test_result_screen_cannot_send_a_new_combat_target(self):
        self.view.set_snapshot(replace(self.snapshot, phase="victory"))
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center), (True, None))

    def test_background_and_right_mouse_button_do_not_select_targets(self):
        self.assertEqual(self.click((3, 3)), (False, None))
        self.assertEqual(self.click(self.view.enemy_hits[0][0].center, button=3), (False, None))

    def test_hover_has_no_combat_side_effect(self):
        event = self.pg.event.Event(self.pg.MOUSEMOTION, pos=self.view.enemy_hits[1][0].center, rel=(0, 0), buttons=(0, 0, 0))
        self.assertEqual(self.view.handle_event(event), (False, None))
        self.assertEqual(self.view.hovered_id, "enemy_1")
        self.assertEqual(self.snapshot.target_id, "enemy_0")

    def test_focus_loss_clears_enemy_and_party_hover_without_changing_target(self):
        rect = next(rect for rect, actor_id in self.view.party_hits if actor_id == "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.assertEqual(self.view.hovered_actor_id, "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        self.assertIsNone(self.view.hovered_actor_id)
        self.assertIsNone(self.view.hovered_id)
        self.assertIsNone(self.view._mouse)
        self.assertEqual(self.view.snapshot.target_id, "enemy_0")

    def test_one_to_three_enemy_cards_fit_at_supported_window_sizes(self):
        for size in ((419, 290), (480, 420), (620, 480), (820, 530)):
            for count in (1, 2, 3):
                canvas = self.pg.Rect(10, 15, *size)
                self.view.set_snapshot(battle_snapshot(count))
                result = self.view.draw(self.surface, canvas)
                self.assertEqual(result, canvas)
                cards = [rect for rect, _ in self.view.enemy_hits]
                self.assertEqual(len(cards), count)
                self.assertTrue(all(canvas.contains(rect) for rect in cards))
                self.assertTrue(all(not first.colliderect(second) for first, second in zip(cards, cards[1:])))

    def test_reduced_motion_is_visually_stable_across_clock_times(self):
        self.view.update(0, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 20)
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1700)
        second = self.pg.image.tobytes(self.surface, "RGB")
        self.assertEqual(first, second)

    def test_unavailable_companions_do_not_appear_in_the_fighting_party(self):
        for companions in (
            (replace(self.snapshot.companions[0], available=True), replace(self.snapshot.companions[1], available=False)),
            tuple(replace(companion, available=False) for companion in self.snapshot.companions),
        ):
            self.view.set_snapshot(replace(self.snapshot, companions=companions))
            self.view.draw(self.surface, self.canvas)
            self.assertEqual(set(self.view.actor_positions) & {"mara", "tobin"}, {companion.id for companion in companions if companion.available})

    def test_normal_mode_has_slow_live_actor_and_environment_motion(self):
        self.view.update(0, reduced_motion=False)
        self.view.draw(self.surface, self.canvas, 20)
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1700)
        self.assertNotEqual(first, self.pg.image.tobytes(self.surface, "RGB"))

    def test_compact_target_marker_and_party_hit_areas_fit_inside_arena(self):
        for size in ((419, 290), (480, 420), (620, 480)):
            canvas = self.pg.Rect(14, 14, *size)
            self.view.draw(self.surface, canvas, 200)
            self.assertIsNotNone(self.view.target_marker_rect)
            self.assertTrue(self.view._arena_rect.contains(self.view.target_marker_rect))
            self.assertEqual({actor_id for _, actor_id in self.view.party_hits}, {"player", "mara", "tobin"})
            self.assertTrue(all(self.view._arena_rect.contains(rect) for rect, _ in self.view.party_hits))

    def test_formation_results_are_bounded_and_clear_of_condition_badges(self):
        for size in ((419, 290), (620, 480)):
            for kind in ("defend", "heal"):
                self.view.set_snapshot(None)
                self.view.set_snapshot(self.snapshot)
                self.view.queue_feedback(CombatFeedback(kind, "player", "player", 5 if kind == "heal" else 0, "Your action."))
                self.view.queue_feedback(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
                for index in range(3):
                    self.view.queue_feedback(CombatFeedback("damage", f"enemy_{index}", "player", index + 3, "Heavy Blow"))
                age = 0
                for when in (0, 0.19, 0.38, 0.57, 0.76, 0.95, 1.14):
                    self.view.update(when - age)
                    age = when
                    self.view.draw(self.surface, self.pg.Rect(14, 14, *size), 200)
                    self.assertLessEqual(len(self.view.feedback_rects), 2)
                    self.assertTrue(all(self.view._arena_rect.contains(rect) for rect in self.view.feedback_rects))
                    self.assertTrue(all(not rect.colliderect(badge) for rect in self.view.feedback_rects for badge, _ in self.view.condition_hits))
                    if len(self.view.feedback_rects) == 2:
                        self.assertFalse(self.view.feedback_rects[0].colliderect(self.view.feedback_rects[1]))
                self.assertEqual(self.view.snapshot, self.snapshot)

    def test_melee_reaches_the_target_before_damage_label_and_returns(self):
        self.view.update(0, reduced_motion=False)
        self.view.draw(self.surface, self.canvas, 0)
        start = self.view.actor_rects["player"].centerx
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 7, "Mira strikes."))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertGreater(self.view.actor_rects["player"].centerx, start + 50)
        self.assertEqual(self.view.feedback_rects, [], "numbers should land at the weapon impact")
        self.view.update(0.06)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(len(self.view.feedback_rects), 1)
        self.view.update(0.3)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.actor_rects["player"].centerx, start)

    def test_combat_sound_cues_land_once_at_the_visible_impact(self):
        self.view.queue_feedback(CombatFeedback("damage", "mara", "enemy_0", 8, "Mara strikes."))
        self.view.queue_feedback(CombatFeedback("interrupt", "player", "enemy_0", 0, "Intent interrupted"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_1", "player", 4, "Heavy Blow"))
        self.view.update(0.17)
        self.assertEqual(self.view.drain_cues(), ())
        self.view.update(0.02)
        self.assertEqual(self.view.drain_cues(), ("hit", "interrupt"))
        self.view.update(0.4)
        self.assertEqual(self.view.drain_cues(), ("hit",))
        self.view.update(0.2)
        self.assertEqual(self.view.drain_cues(), ())
        self.assertEqual(self.view.snapshot, self.snapshot)

    def test_silent_frontends_keep_the_sound_cue_queue_bounded(self):
        for _ in range(25):
            self.view.queue_feedback(CombatFeedback("defend", "player", "player", 0, "Guard"))
        self.view.update(1)
        self.assertEqual(len(self.view.drain_cues()), 16)
        self.assertEqual(self.view.drain_cues(), ())
        self.view.queue_feedback(CombatFeedback("heal", "player", "player", 4, "Remedy"))
        self.view.update(0.1)
        self.view.set_snapshot(None)
        self.assertEqual(self.view.drain_cues(), ())

    def test_block_and_bleeding_have_distinct_sound_cues_in_reduced_motion(self):
        self.view.update(0, reduced_motion=True)
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 0, "Ward absorbs the hit"))
        self.view.queue_feedback(CombatFeedback("damage", "player", "player", 1, "Bleeding"))
        self.view.update(0.1, reduced_motion=True)
        self.assertEqual(self.view.drain_cues(), ("block", "hurt"))

    def test_final_snapshot_preserves_the_foe_until_the_killing_hit_lands(self):
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 12, "Final strike"))
        self.view.queue_feedback(CombatFeedback("fallen", "player", "enemy_0", 0, "The captain falls."))
        fallen = replace(self.snapshot.enemies[0], hp=0)
        self.view.set_snapshot(replace(self.snapshot, phase="victory", enemies=(fallen, *self.snapshot.enemies[1:])))
        self.assertEqual(self.view._fall_progress("enemy_0", False), 0)
        self.assertTrue(self.view.busy)
        self.view.update(0.3)
        self.assertGreater(self.view._fall_progress("enemy_0", False), 0)
        self.assertLess(self.view._fall_progress("enemy_0", False), 1)
        self.view.update(0.6)
        self.assertEqual(self.view._fall_progress("enemy_0", False), 1)
        self.assertFalse(self.view.busy)

    def test_paid_action_gate_has_a_short_bound_and_targeting_stays_free(self):
        for reduced, maximum in ((False, self.view.MAX_TURN_DURATION), (True, self.view.REDUCED_MOTION_TURN_DURATION)):
            self.view.set_snapshot(None)
            self.view.set_snapshot(self.snapshot)
            self.view.update(0, reduced_motion=reduced)
            for _ in range(12):
                self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 1, "Formation attack"))
            self.assertTrue(self.view.has_pending_feedback)
            self.view.draw(self.surface, self.canvas, 0)
            self.assertEqual(self.click(self.view.enemy_hits[1][0].center), (True, "enemy_1"))
            self.view.update(maximum + 0.01, reduced_motion=reduced)
            self.assertFalse(self.view.has_pending_feedback)

    def test_a_new_committed_move_does_not_sum_the_previous_rounds_labels(self):
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 8, "First round"))
        self.view.update(0.6)
        self.assertFalse(self.view.busy)
        self.assertEqual(len(self.view._effects), 1, "the first round's popup can still linger")
        self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_1", 4, "Next committed move"))
        self.assertEqual(len(self.view._effects), 1)
        self.assertEqual(self.view._effects[0].feedback.amount, 4)

    def test_zero_health_remedy_still_shows_a_meaningful_action_result(self):
        text, _ = self.view._feedback_label(CombatFeedback("heal", "player", "player", 0, "Field Remedy"))
        self.assertEqual(text, "REMEDY")

    def test_interrupt_result_remains_readable_when_bleeding_ticks_follow_it(self):
        self.view.queue_feedback(CombatFeedback("damage", "mara", "enemy_0", 8, "Mara crosses blades."))
        self.view.queue_feedback(CombatFeedback("interrupt", "player", "enemy_0", 0, "Iron Guard interrupted"))
        self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "enemy_0", 1, "Bleeding costs 1 Health."))
        self.view.update(0.74)
        self.view.draw(self.surface, self.pg.Rect(14, 14, 419, 290), 0)
        labels = [text for actor_id, text, _ in self.view.feedback_labels if actor_id == "enemy_0"]
        self.assertIn("INTERRUPTED", labels)
        self.assertIn("−9 ×2", labels)
        self.assertTrue(all(self.view._arena_rect.contains(rect) for rect in self.view.feedback_rects))

    def test_guard_result_survives_a_formation_of_three_incoming_hits(self):
        self.view.queue_feedback(CombatFeedback("defend", "player", "player", 1, "You defend."))
        for index, damage in enumerate((1, 2, 4)):
            self.view.queue_feedback(CombatFeedback("damage", f"enemy_{index}", "player", damage, "Heavy Blow"))
        self.view.update(0.78)
        self.view.draw(self.surface, self.canvas, 0)
        labels = [text for actor_id, text, _ in self.view.feedback_labels if actor_id == "player"]
        self.assertIn("GUARDED", labels)
        self.assertIn("−7 ×3", labels)

    def test_health_loss_trail_is_visual_and_reduced_motion_snaps_it(self):
        damaged = replace(self.snapshot.enemies[0], hp=6)
        self.view.set_snapshot(replace(self.snapshot, enemies=(damaged, *self.snapshot.enemies[1:])))
        self.assertEqual(self.view._health_trails["enemy_0"], 12)
        self.assertEqual(self.view.snapshot.enemies[0].hp, 6)
        self.view.update(0.4)
        self.assertGreater(self.view._health_trails["enemy_0"], 6)
        self.assertLess(self.view._health_trails["enemy_0"], 12)
        self.view.update(0, reduced_motion=True)
        self.assertEqual(self.view._health_trails["enemy_0"], 6)

    def test_defensive_objective_does_not_advertise_unavailable_attacks(self):
        actions = tuple(action for action in self.snapshot.actions if action.id == "defend")
        self.view.set_snapshot(replace(self.snapshot, actions=actions, defensive_objective=True))
        self.view.draw(self.surface, self.canvas, 200)
        help_text = self.view._intent_help(self.snapshot.enemies[0])
        self.assertIn("Defend", help_text)
        self.assertNotIn("Power Attack", help_text)
        self.assertNotIn("Mara", help_text)
        self.assertEqual(self.view._interrupt_label(self.snapshot.enemies[0]), "◇ HOLD YOUR GROUND")

    def test_survival_victory_caption_explains_the_living_invulnerable_foe(self):
        self.view.set_snapshot(replace(self.snapshot, phase="victory", defensive_objective=True, max_rounds=3, round_number=3))
        rendered = []
        original = self.view._text

        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
            rendered.append(str(text))
            original(surface, text, pos, color, font=font)

        self.view._text = record
        self.view.draw(self.surface, self.canvas, 0)
        self.assertIn("YOU HELD THE LINE", rendered)
        self.assertEqual(self.view.snapshot.enemies[0].hp, 12)

    def test_intent_disruption_help_uses_enabled_commands_only(self):
        actions = tuple(replace(action, enabled=False, disabled_reason="Not enough Focus.") if action.id in {"power", "mara"} else action for action in self.snapshot.actions)
        self.view.set_snapshot(replace(self.snapshot, actions=actions))
        text = self.view._intent_help(self.snapshot.enemies[0])
        self.assertIn("no disruption is currently available", text)
        self.assertNotIn("Power Attack or Mara", text)
        self.assertEqual(self.view._interrupt_label(self.snapshot.enemies[0]), "◆ INTERRUPTIBLE")

    def test_companion_hover_explains_role_bond_and_disabled_command(self):
        action = replace(self.snapshot.actions[-1], enabled=False, disabled_reason="Not enough Focus.")
        self.view.set_snapshot(replace(self.snapshot, actions=(*self.snapshot.actions[:-1], action)))
        self.view.draw(self.surface, self.canvas, 200)
        rect = next(rect for rect, actor_id in self.view.party_hits if actor_id == "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.assertEqual(self.view.hovered_actor_id, "mara")
        text = self.view._party_help("mara")
        self.assertIn("Bond 3", text)
        self.assertIn(action.description, text)
        self.assertIn("Not enough Focus", text)

    def test_long_party_tooltip_fits_with_all_actual_status_rules(self):
        from roads_beneath_shadow.combat_view import STATUS_DESCRIPTIONS
        statuses = tuple(CombatStatusView(key, key.title(), 2, STATUS_DESCRIPTIONS[key]) for key in ("bleeding", "exposed", "evade", "ward", "riposte"))
        self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, statuses=statuses)))
        canvas = self.pg.Rect(14, 14, 419, 290)
        self.view.draw(self.surface, canvas, 200)
        actor = next(rect for rect, actor_id in self.view.party_hits if actor_id == "player")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=actor.center, rel=(0, 0), buttons=(0, 0, 0)))
        rendered = []
        original = self.view._text

        def record(surface, text, pos, color=(239, 225, 188), *, font=None):
            if self.view.tooltip_rect is not None:
                glyph = (font or self.view.font).render(str(text), True, color)
                rendered.append((str(text), self.pg.Rect(*pos, glyph.get_width(), glyph.get_height())))
            original(surface, text, pos, color, font=font)

        self.view._text = record
        self.view.draw(self.surface, canvas, 200)
        self.assertIsNotNone(self.view.tooltip_rect)
        self.assertTrue(canvas.contains(self.view.tooltip_rect))
        self.assertTrue(all(self.view.tooltip_rect.contains(bounds) for _, bounds in rendered))
        text = " ".join(line for line, _ in rendered)
        for status in statuses:
            self.assertIn(status.description, text)

    def test_enemy_sprite_hover_shows_its_name_and_tactics(self):
        rect, enemy_id = self.view.sprite_hits[1]
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=rect.center, rel=(0, 0), buttons=(0, 0, 0)))
        self.view.draw(self.surface, self.canvas, 200)
        text = next(text for hit, text in self.view.tooltip_hits if hit.collidepoint(rect.center))
        self.assertIn(self.snapshot.enemies[1].name, text)
        self.assertIn(self.snapshot.enemies[1].telegraph, text)
        self.assertTrue(self.canvas.contains(self.view.tooltip_rect))

    def test_evaded_enemy_attack_has_a_sidestep_and_no_health_mutation(self):
        self.view.draw(self.surface, self.canvas, 0)
        player_x = self.view.actor_rects["player"].centerx
        enemy_x = self.view.actor_rects["enemy_0"].centerx
        self.view.queue_feedback(CombatFeedback("evade", "enemy_0", "player", 0, "Attack evaded"))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertLess(self.view.actor_rects["player"].centerx, player_x)
        self.assertLess(self.view.actor_rects["enemy_0"].centerx, enemy_x - 50)
        self.assertEqual(self.view.snapshot.player.hp, 17)
        self.view.update(0.4)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.actor_rects["player"].centerx, player_x)

    def test_escaping_party_retreats_and_stays_out_after_the_cue_expires(self):
        self.view.draw(self.surface, self.canvas, 0)
        player_x = self.view.actor_rects["player"].centerx
        self.view.queue_feedback(CombatFeedback("escape", "player", "player", 0, "You find an opening and escape."))
        self.view.set_snapshot(replace(self.snapshot, phase="escaped"))
        self.view.update(0.14)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertLess(self.view.actor_rects["player"].centerx, player_x)
        self.assertEqual(self.view.snapshot.player.hp, 17)
        self.view.update(2)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.party_hits, [])
        self.assertNotIn("player", self.view.actor_rects)

    def test_reduced_motion_escape_settles_without_a_moving_party(self):
        self.view.queue_feedback(CombatFeedback("escape", "player", "player", 0, "You find an opening and escape."))
        self.view.set_snapshot(replace(self.snapshot, phase="escaped"))
        self.view.update(0.1, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 0)
        self.assertEqual(self.view.party_hits, [])
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.view.draw(self.surface, self.canvas, 1900)
        self.assertEqual(first, self.pg.image.tobytes(self.surface, "RGB"))

    def test_health_trail_waits_for_a_late_formation_hit(self):
        for _ in range(5):
            self.view.queue_feedback(CombatFeedback("damage", "enemy_0", "player", 1, "Formation attack"))
        self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, hp=12)))
        self.view.update(0.4)
        self.assertEqual(self.view._health_trails["player"], 17)
        self.view.update(0.6)
        self.assertLess(self.view._health_trails["player"], 17)
        self.assertEqual(self.view.snapshot.player.hp, 12)

    def test_origin_and_equipped_weapon_change_the_shared_traveler_sprite(self):
        images = []
        for origin in ("bree_wayfarer", "north_road_scout", "healers_apprentice"):
            self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, origin=origin)))
            images.append(self.pg.image.tobytes(self.view._sprite("player", False), "RGBA"))
        self.assertEqual(len(set(images)), 3)
        images = []
        for weapon in (None, "rusty_sword", "knife", "ash_staff"):
            self.view.set_snapshot(replace(self.snapshot, player=replace(self.snapshot.player, weapon_id=weapon)))
            images.append(self.pg.image.tobytes(self.view._sprite("player", False), "RGBA"))
        self.assertEqual(len(set(images)), 4)

    def test_damage_feedback_draws_then_expires_without_changing_snapshot(self):
        for canvas in (self.canvas, self.pg.Rect(19, 91, 419, 290)):
            self.view.update(0, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            before = self.pg.image.tobytes(self.surface, "RGB")
            self.view.queue_feedback(CombatFeedback("damage", "player", "enemy_0", 7, "Mira strikes the captain."))
            self.view.update(0.1, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            self.assertNotEqual(before, self.pg.image.tobytes(self.surface, "RGB"))
            self.assertEqual(self.snapshot.enemies[0].hp, 12)
            self.view.update(3, reduced_motion=True)
            self.view.draw(self.surface, canvas, 200)
            self.assertEqual(before, self.pg.image.tobytes(self.surface, "RGB"))

    def test_status_and_intent_tooltips_include_the_actual_rules(self):
        text = "\n".join(text for _, text in self.view.tooltip_hits)
        self.assertIn("Lose 1 Health at the start of each turn", text)
        self.assertIn("Defend or interrupt it", text)
        self.assertIn("Power Attack or Mara", text)

    def test_inspection_and_notice_messages_do_not_animate_a_combat_hit(self):
        self.view.update(0, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 200)
        before = self.pg.image.tobytes(self.surface, "RGB")
        for kind in ("inspect", "notice", "info"):
            self.view.queue_feedback(CombatFeedback(kind, "player", "enemy_0", 0, "Read the enemy's tactics."))
        self.view.update(0.1, reduced_motion=True)
        self.view.draw(self.surface, self.canvas, 200)
        self.assertEqual(before, self.pg.image.tobytes(self.surface, "RGB"))

    def test_protected_damage_forecast_still_says_zero_damage(self):
        enemy = replace(self.snapshot.enemies[0], damage_min=0, damage_max=0, threat="danger")
        self.view.set_snapshot(replace(self.snapshot, enemies=(enemy,)))
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            rendered.append(str(text))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        self.view.draw(self.surface, self.canvas)
        self.assertIn("0–0 DAMAGE", rendered)

    def test_small_three_enemy_canvas_keeps_long_intents_and_statuses_visible(self):
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        enemies = tuple(replace(enemy, name=("Ash-Hand Commander", "Ash-Hand Sapper", "Ash-Hand Archer")[index],
                                intent_label="Ash-Hand Execution", telegraph="a devastating blow; interrupt it now", statuses=(guarded,))
                        for index, enemy in enumerate(self.snapshot.enemies))
        self.view.set_snapshot(replace(self.snapshot, enemies=enemies))
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            if text == "Guarded 2":
                rendered.append((pos, (font or self.view.font).get_linesize()))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        for size in ((480, 420), (419, 290)):
            rendered.clear()
            self.view.draw(self.surface, self.pg.Rect(14, 14, *size))
            self.assertEqual(len(rendered), 3)
            for (pos, line_height), (card, _) in zip(rendered, self.view.enemy_hits):
                self.assertTrue(card.contains(self.pg.Rect(*pos, 50, line_height)))

    def test_larger_platform_font_metrics_keep_every_enemy_card_field_visible(self):
        # Emulate a platform resolving the same requested system family to a
        # taller, wider font. These are real SDL fonts and glyph surfaces.
        self.view.mini_bold_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 18, bold=True)
        self.view.mini_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        self.view.mini_prose_font = self.pg.font.SysFont("dejavusans,arial,sans", 17)
        guarded = CombatStatusView("guarded", "Guarded", 2, "+2 Armor until struck.")
        weakened = CombatStatusView("weakened", "Weakened", 1, "Reduce incoming attacks by 2.")
        enemy = replace(self.snapshot.enemies[0], name="Ash-Hand Commander", phase=2,
                        intent_label="Ash-Hand Execution", telegraph="a devastating blow; interrupt it now",
                        statuses=(guarded, weakened))
        card = self.pg.Rect(14, 14, 134, 164)
        fonts = (self.view.mini_bold_font, self.view.mini_font, self.view.mini_prose_font)
        self.assertGreater(self.view._card_content_height(card, enemy, False, True, fonts), card.h)
        rendered = []
        original_text = self.view._text

        def record_text(surface, text, pos, color=(239, 225, 188), *, font=None):
            selected_font = font or self.view.font
            glyph = selected_font.render(str(text), True, color)
            rendered.append((str(text), self.pg.Rect(*pos, glyph.get_width(), max(glyph.get_height(), selected_font.get_linesize()))))
            original_text(surface, text, pos, color, font=font)

        self.view._text = record_text
        self.view._draw_card(self.surface, card, enemy)
        self.assertTrue(all(card.contains(glyph_rect) for _, glyph_rect in rendered), rendered)
        text = " ".join(text for text, _ in rendered)
        for field in (enemy.name, "HEALTH", "ARMOR", "PHASE", enemy.intent_label.upper(), "DAMAGE", enemy.telegraph, "CAN INTERRUPT", "Guarded 2", "Weakened 1"):
            self.assertIn(field, text)

    def test_fitted_font_measurements_match_its_actual_rendered_glyphs(self):
        from roads_beneath_shadow.pixel_battle import _ScaledFont
        native = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        fitted = _ScaledFont(self.pg, native, 0.73)
        for text in ("Ash-Hand Commander", "◆ CAN INTERRUPT", "Guarded 2"):
            glyph = fitted.render(text, True, (239, 225, 188))
            self.assertEqual(fitted.size(text), glyph.get_size())
            self.assertGreaterEqual(fitted.get_linesize(), glyph.get_height())

    def test_animation_frames_reuse_measured_card_typography(self):
        self.view.mini_font = self.pg.font.SysFont("dejavusansmono,courier,monospace", 17)
        enemy = self.snapshot.enemies[0]
        card = self.pg.Rect(14, 14, 134, 164)
        with patch.object(self.view, "_card_content_height", wraps=self.view._card_content_height) as measure:
            self.view._draw_card(self.surface, card, enemy)
            first_frame_calls = measure.call_count
            self.assertGreater(first_frame_calls, 1)
            self.view._draw_card(self.surface, card, enemy)
            self.assertEqual(measure.call_count, first_frame_calls)
            self.view.set_snapshot(replace(self.snapshot, round_number=3))
            self.view._draw_card(self.surface, card, enemy)
            self.assertGreater(measure.call_count, first_frame_calls)

    def test_original_sprite_styles_distinguish_enemy_roles(self):
        sprites = [self.view._sprite(kind, True) for kind in ("orc", "captain", "archer", "sapper", "warg", "ghorak", "troll", "rider")]
        self.assertEqual(len({self.pg.image.tobytes(sprite, "RGBA") for sprite in sprites}), 8)
        self.assertTrue(all(sprite.get_flags() & self.pg.SRCALPHA for sprite in sprites))

    def test_draw_restores_the_callers_clip_and_never_paints_outside_canvas(self):
        sentinel = (222, 6, 203)
        self.surface.fill(sentinel)
        original_clip = self.pg.Rect(3, 3, 900, 700)
        self.surface.set_clip(original_clip)
        self.view.draw(self.surface, self.canvas)
        self.assertEqual(self.surface.get_clip(), original_clip)
        self.assertEqual(tuple(self.surface.get_at((self.canvas.x - 1, self.canvas.y))[:3]), sentinel)
        self.assertEqual(tuple(self.surface.get_at((self.canvas.right, self.canvas.y))[:3]), sentinel)

    def test_leaving_combat_clears_old_clickable_targets(self):
        self.view.queue_feedback(CombatFeedback("heal", "player", "player", 5, "A remedy restores Health."))
        self.view.set_snapshot(None)
        self.assertEqual(self.click(self.canvas.center), (False, None))
        self.assertEqual(self.view.enemy_hits, [])
        self.assertEqual(self.view.actor_positions, {})

    def test_long_enemy_names_are_wrapped_without_losing_words(self):
        name = "Teren the False Ranger and keeper of the drowned gate"
        lines = _wrapped(name, self.view.font, 146)
        self.assertEqual(" ".join(lines), name)
        self.assertTrue(all(self.view.font.size(line)[0] <= 146 for line in lines))


if __name__ == "__main__":
    unittest.main()
