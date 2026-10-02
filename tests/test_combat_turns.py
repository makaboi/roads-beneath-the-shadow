"""Regressions for free combat interactions and structured presentation data."""

import random
import unittest
from dataclasses import FrozenInstanceError

from roads_beneath_shadow.combat import CombatConfig, CombatDifficulty, CombatEngine, CombatResult
from roads_beneath_shadow.combat_view import CombatCommand, CombatFeedback, CombatSnapshot
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.ui import TerminalUI


class CombatViewUI(TerminalUI):
    def __init__(self, actions, *, target=2):
        self.output = []
        self.snapshots: list[CombatSnapshot] = []
        self.feedback: list[CombatFeedback] = []
        self.actions = iter(actions)
        self.target = target
        super().__init__(color=False, fast=True, output_fn=self.output.append)

    def combat_snapshot(self, snapshot):
        self.snapshots.append(snapshot)

    def combat_feedback(self, feedback):
        self.feedback.append(feedback)

    def choose(self, title, options, *, allow_back=False):
        if title == "Choose your action":
            action = next(self.actions)
            return next(index + 1 for index, view in enumerate(self.snapshots[-1].actions) if view.id == action)
        if title == "Choose a target":
            return self.target
        if title == "Use which item?":
            return None
        raise AssertionError(f"Unexpected menu: {title}")


class CombatTurnTests(unittest.TestCase):
    @staticmethod
    def state(origin=0):
        return GameState(Character.from_origin("Arin", ORIGINS[origin]))

    def test_inspect_target_and_cancelled_item_leave_round_and_bleeding_unchanged(self):
        ui = CombatViewUI(["mara", "inspect", "target", "item", "defend"])
        state = self.state()
        state.character.hp -= 1
        enemies = [
            Enemy("Same name", 100, 100, 1, 1, intent_pattern=("heavy",)),
            Enemy("Same name", 100, 100, 1, 1, intent_pattern=("aim",)),
        ]

        result = CombatEngine(ui, random.Random(1)).run(
            state, enemies, CombatConfig(mara_aid=True, max_rounds=2)
        )

        self.assertEqual(result, CombatResult.VICTORY)
        second_round = [snapshot for snapshot in ui.snapshots if snapshot.round_number == 2 and snapshot.phase == "active"]
        self.assertEqual(len(second_round), 4)
        self.assertEqual(len({snapshot.enemies[0].hp for snapshot in second_round}), 1)
        self.assertEqual(len({snapshot.enemies[0].intent_id for snapshot in second_round}), 1)
        self.assertTrue(all(snapshot.enemies[0].statuses[0].remaining == 1 for snapshot in second_round))
        self.assertEqual(second_round[0].target_id, "enemy_0")
        self.assertEqual(second_round[-1].target_id, "enemy_1")
        self.assertEqual([enemy.turn_count for enemy in enemies], [2, 2])
        self.assertEqual(sum("loses 1 Health from Bleeding" in line for line in ui.output), 1)

    def test_cancelled_target_does_not_advance_effects_or_enemy_turn(self):
        ui = CombatViewUI(["mara", "target", "inspect", "defend"], target=None)
        enemies = [
            Enemy("First", 100, 100, 1, 1, intent_pattern=("heavy",)),
            Enemy("Second", 100, 100, 1, 1, intent_pattern=("aim",)),
        ]
        CombatEngine(ui, random.Random(1)).run(self.state(), enemies, CombatConfig(mara_aid=True, max_rounds=2))
        rounds = [snapshot for snapshot in ui.snapshots if snapshot.round_number == 2 and snapshot.phase == "active"]
        self.assertEqual(len({snapshot.enemies[0].hp for snapshot in rounds}), 1)
        self.assertTrue(all(snapshot.target_id == "enemy_0" for snapshot in rounds))
        self.assertEqual(enemies[0].turn_count, 2)

    def test_graphical_inspection_opens_read_only_details_without_advancing_turn(self):
        class InspectionUI(CombatViewUI):
            def __init__(self):
                super().__init__(["inspect", "defend"])
                self.panels = []

            def show_panel(self, kind, data):
                self.panels.append((kind, data))
                return {"action": "close"}

        ui = InspectionUI()
        enemy = Enemy("Chain Hunter", 40, 40, 4, 4, armor=3, description="A hunter bound to the floodgate.", intent_pattern=("heavy",))
        CombatEngine(ui, random.Random(2)).run(self.state(), [enemy], CombatConfig(max_rounds=1))
        self.assertEqual(enemy.turn_count, 1)
        self.assertEqual(ui.panels[0][0], "information")
        self.assertEqual(ui.panels[0][1]["title"], "Chain Hunter")
        prose = " ".join(section["text"] for section in ui.panels[0][1]["sections"])
        self.assertIn("Armor 3", prose)
        self.assertIn("can be interrupted", prose)
        self.assertIn(enemy.description, prose)
        self.assertEqual([snapshot.round_number for snapshot in ui.snapshots if snapshot.phase == "active"], [1, 1])
        inspect = next(event for event in ui.feedback if event.kind == "inspect")
        self.assertEqual((inspect.actor_id, inspect.target_id), ("player", "enemy_0"))

    def test_graphical_target_clicks_are_free_and_keep_stable_enemy_ids(self):
        class ClickUI(CombatViewUI):
            def choose_combat(self, options):
                action = next(self.actions)
                if isinstance(action, CombatCommand):
                    return action
                return next(index + 1 for index, view in enumerate(self.snapshots[-1].actions) if view.id == action)

        ui = ClickUI([
            "mara", CombatCommand("target", "enemy_1"),
            CombatCommand("target", "enemy_missing"),
            CombatCommand("target", "enemy_0"), "defend",
        ])
        enemies = [
            Enemy("Same name", 100, 100, 1, 1, intent_pattern=("heavy",)),
            Enemy("Same name", 100, 100, 1, 1, intent_pattern=("aim",)),
        ]
        CombatEngine(ui, random.Random(1)).run(self.state(), enemies, CombatConfig(mara_aid=True, max_rounds=2))
        rounds = [snapshot for snapshot in ui.snapshots if snapshot.round_number == 2 and snapshot.phase == "active"]
        self.assertEqual([snapshot.target_id for snapshot in rounds], ["enemy_0", "enemy_1", "enemy_1", "enemy_0"])
        self.assertEqual(len({snapshot.enemies[0].hp for snapshot in rounds}), 1)
        self.assertEqual([enemy.turn_count for enemy in enemies], [2, 2])

    def test_insufficient_focus_retries_do_not_tick_bleeding(self):
        ui = CombatViewUI(["mara", "power", "origin", "mara", "defend"])
        state = self.state()
        state.character.max_focus = 1
        enemy = Enemy("Crusher", 100, 100, 1, 1, intent_pattern=("heavy",))

        CombatEngine(ui, random.Random(1)).run(state, [enemy], CombatConfig(mara_aid=True, max_rounds=2))

        rounds = [snapshot for snapshot in ui.snapshots if snapshot.round_number == 2 and snapshot.phase == "active"]
        self.assertEqual(len(rounds), 4)
        self.assertEqual(len({snapshot.enemies[0].hp for snapshot in rounds}), 1)
        actions = {action.id: action for action in rounds[0].actions}
        self.assertFalse(actions["power"].enabled)
        self.assertFalse(actions["origin"].enabled)
        self.assertFalse(actions["mara"].enabled)
        self.assertTrue(actions["defend"].enabled)
        self.assertEqual(actions["power"].disabled_reason, "Requires 1 Focus")
        self.assertEqual(enemy.turn_count, 2)
        self.assertEqual(sum(event.kind == "notice" for event in ui.feedback), 3)

    def test_enemy_bleeding_still_ticks_once_for_each_committed_round(self):
        ui = CombatViewUI(["mara", "inspect", "defend", "defend"])
        enemy = Enemy("Crusher", 100, 100, 1, 1, intent_pattern=("heavy",))
        CombatEngine(ui, random.Random(1)).run(self.state(), [enemy], CombatConfig(mara_aid=True, max_rounds=3))
        ticks = [event for event in ui.feedback if event.kind == "damage" and event.actor_id == event.target_id == "enemy_0"]
        self.assertEqual([event.amount for event in ticks], [1, 1])
        self.assertNotIn("bleeding", enemy.statuses)
        self.assertEqual(enemy.turn_count, 3)

    def test_snapshots_are_immutable_and_feedback_uses_stable_entity_ids(self):
        ui = CombatViewUI(["attack"])
        state = self.state()
        result = CombatEngine(ui, random.Random(2)).run(state, [Enemy("Practice", 1, 1, 1, 1)])
        self.assertEqual(result, CombatResult.VICTORY)
        first = ui.snapshots[0]
        self.assertEqual((first.player.weapon_id, first.player.armor), ("ash_staff", 1))
        self.assertEqual(first.target_id, first.enemies[0].id)
        self.assertEqual(ui.snapshots[-1].phase, "victory")
        self.assertEqual(ui.snapshots[-1].enemies[0].hp, 0)
        self.assertEqual([(event.kind, event.actor_id, event.target_id) for event in ui.feedback], [
            ("damage", "player", "enemy_0"), ("fallen", "player", "enemy_0"),
        ])
        with self.assertRaises(FrozenInstanceError):
            first.player.hp = 0
        self.assertEqual(first.enemies[0].hp, 1)

    def test_snapshot_forecasts_announced_hits_without_consuming_rng_or_statuses(self):
        ui = CombatViewUI(["attack"])
        enemy = Enemy("Heavy", 100, 100, 4, 7, intent_pattern=("heavy",))
        rng = random.Random(12)
        engine = CombatEngine(ui, rng, CombatDifficulty.HARD)
        state = self.state()
        before = rng.getstate()
        result = engine.run(state, [enemy], CombatConfig(max_rounds=1))
        # A normal attack and one enemy attack are the encounter's only draws.
        expected_rng = random.Random()
        expected_rng.setstate(before)
        expected_rng.randint(1, 3)
        expected_rng.randint(4, 7)
        self.assertEqual(rng.getstate(), expected_rng.getstate())
        self.assertEqual(result, CombatResult.VICTORY)
        forecast = ui.snapshots[0].enemies[0]
        self.assertEqual((forecast.damage_min, forecast.damage_max), (7, 10))
        self.assertEqual((forecast.intent_id, forecast.threat, forecast.interruptible), ("heavy", "danger", True))
        actual = next(event.amount for event in ui.feedback if event.target_id == "player")
        self.assertLessEqual(forecast.damage_min, actual)
        self.assertGreaterEqual(forecast.damage_max, actual)

    def test_defensive_objective_snapshot_preserves_rider_and_action_limits(self):
        ui = CombatViewUI(["defend"])
        enemy = Enemy("Rider", 999, 999, 4, 4, intent_pattern=("heavy",))
        result = CombatEngine(ui, random.Random(3)).run(
            self.state(), [enemy], CombatConfig(
                max_rounds=1, objective_enemy_invulnerable=True,
                objective="Hold the seal", mara_aid=True, tobin_aid=True,
            )
        )
        snapshot = ui.snapshots[0]
        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual((snapshot.objective, snapshot.max_rounds, snapshot.defensive_objective), ("Hold the seal", 1, True))
        self.assertFalse({"attack", "power", "target", "origin"} & {action.id for action in snapshot.actions})
        self.assertEqual(enemy.hp, 999)
        self.assertEqual({view.id for view in snapshot.companions if view.available}, {"mara", "tobin"})
        self.assertFalse(any(event.target_id == "enemy_0" for event in ui.feedback))

    def test_defensive_companion_commands_add_protection_without_wounding_rider(self):
        class NoPassiveAidRandom(random.Random):
            def randint(self, minimum, maximum):
                return minimum

            def random(self):
                return 1.0

        damage = {}
        for action in ("defend", "mara_guard", "tobin_guard"):
            with self.subTest(action=action):
                ui = CombatViewUI([action])
                state = self.state()
                rider = Enemy("Rider", 999, 999, 8, 8)
                CombatEngine(ui, NoPassiveAidRandom()).run(state, [rider], CombatConfig(
                    max_rounds=1, objective_enemy_invulnerable=True, mara_aid=True, tobin_aid=True,
                ))
                damage[action] = state.character.max_hp - state.character.hp
                self.assertEqual((rider.hp, rider.statuses), (999, {}))
                self.assertFalse(any(event.target_id == "enemy_0" for event in ui.feedback))
                self.assertEqual(state.character.focus, 3 if action == "defend" else 2)
        self.assertEqual(damage, {"defend": 3, "mara_guard": 1, "tobin_guard": 0})

    def test_defensive_companion_effect_protects_one_hit_and_halves_remaining_attacks(self):
        class NoPassiveAidRandom(random.Random):
            def randint(self, minimum, maximum):
                return minimum

            def random(self):
                return 1.0

        for action, expected in (("mara_guard", [1, 3]), ("tobin_guard", [3])):
            with self.subTest(action=action):
                ui = CombatViewUI([action])
                enemies = [Enemy("First", 999, 999, 8, 8), Enemy("Second", 999, 999, 8, 8)]
                CombatEngine(ui, NoPassiveAidRandom()).run(self.state(), enemies, CombatConfig(
                    max_rounds=1, objective_enemy_invulnerable=True, mara_aid=True, tobin_aid=True,
                ))
                hits = [event.amount for event in ui.feedback if event.kind == "damage" and event.target_id == "player"]
                self.assertEqual(hits, expected)
                self.assertFalse(ui.snapshots[-1].player.statuses)


if __name__ == "__main__":
    unittest.main()
