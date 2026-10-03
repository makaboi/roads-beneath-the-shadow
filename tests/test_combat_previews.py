"""Action forecasts describe real hits without spending a turn or RNG draw."""

from __future__ import annotations

from copy import deepcopy
import random
import unittest

from roads_beneath_shadow.combat import CombatConfig, CombatDifficulty, CombatEngine, CombatResult, chain_troll, ghorak
from roads_beneath_shadow.combat_view import CombatActionView, CombatCommand
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.ui import TerminalUI


class PreviewUI(TerminalUI):
    def __init__(self, actions=(), *, item_choice=1):
        self.output = []
        self.snapshots = []
        self.feedback = []
        self.panels = []
        self.sounds = []
        self.item_options = []
        self.actions = iter(actions)
        self.item_choice = item_choice
        self.on_begin = lambda: None
        self.before_action = lambda: None
        super().__init__(color=False, fast=True, output_fn=self.output.append)

    def combat_begin(self):
        self.on_begin()

    def combat_snapshot(self, snapshot):
        self.snapshots.append(snapshot)

    def combat_feedback(self, event):
        self.feedback.append(event)

    def choose_combat(self, options):
        self.before_action()
        action = next(self.actions)
        if isinstance(action, CombatCommand):
            return action
        return next(index for index, view in enumerate(self.snapshots[-1].actions, 1) if view.id == action)

    def choose(self, title, options, *, allow_back=False):
        if title == "Use which item?":
            self.item_options.append(tuple(options))
            return self.item_choice
        raise AssertionError(f"Unexpected choice: {title}")

    def show_panel(self, kind, data):
        self.panels.append((kind, data))
        return {"action": "close"}

    def sound(self, cue):
        self.sounds.append(cue)


class CombatPreviewTests(unittest.TestCase):
    @staticmethod
    def state(origin=0):
        return GameState(Character.from_origin("Mira", ORIGINS[origin]))

    @staticmethod
    def target(*, armor=3, archetype="boss", intent="guard"):
        return Enemy("Chain Hunter", 100, 100, 2, 2, armor=armor,
                     archetype=archetype, intent_pattern=(intent,))

    def run_one(self, action, *, origin=0, difficulty=CombatDifficulty.NORMAL, seed=0,
                statuses=None, player_statuses=None, intent="guard", config=None):
        state = self.state(origin)
        state.character.mara_trust = 2
        state.character.tobin_trust = 2
        enemy = self.target(intent=intent)
        ui = PreviewUI([action])
        engine = CombatEngine(ui, random.Random(seed), difficulty)

        def setup():
            enemy.statuses.update(statuses or {})
            engine._player_statuses.update(player_statuses or {})

        ui.on_begin = setup
        result = engine.run(state, [enemy], config or CombatConfig(max_rounds=1, mara_aid=True, tobin_aid=True))
        return state, enemy, ui, result

    def test_old_action_constructor_keeps_no_damage_forecast(self):
        view = CombatActionView("inspect", "Inspect", 0, True, "", "Read the target.")
        self.assertIsNone(view.damage_min)
        self.assertIsNone(view.damage_max)
        self.assertFalse(view.damage_conditional)

    def test_guard_vulnerability_and_shadow_resistance_are_in_weapon_preview(self):
        expected = {
            CombatDifficulty.STORY: {"attack": (3, 5), "power": (10, 12)},
            CombatDifficulty.NORMAL: {"attack": (2, 4), "power": (9, 11)},
            CombatDifficulty.HARD: {"attack": (1, 2), "power": (6, 8)},
        }
        for difficulty, forecasts in expected.items():
            for action, bounds in forecasts.items():
                with self.subTest(difficulty=difficulty, action=action):
                    _, _, ui, _ = self.run_one(action, difficulty=difficulty, statuses={"guarded": 1, "vulnerable": 1})
                    forecast = next(view for view in ui.snapshots[0].actions if view.id == action)
                    self.assertEqual((forecast.damage_min, forecast.damage_max), bounds)
                    self.assertFalse(forecast.damage_conditional)
                    self.assertIn("damage to Chain Hunter", forecast.description)

    def test_preview_bounds_contain_real_resolved_hits_for_all_damage_commands(self):
        for difficulty in CombatDifficulty:
            for action, origin, actor in (("attack", 0, "player"), ("power", 0, "player"),
                                          ("origin", 1, "player"), ("mara", 0, "mara"), ("tobin", 0, "tobin")):
                observed = set()
                for seed in range(24):
                    _, _, ui, result = self.run_one(action, origin=origin, difficulty=difficulty, seed=seed,
                                                   statuses={"guarded": 1, "vulnerable": 1})
                    forecast = next(view for view in ui.snapshots[0].actions if view.id == action)
                    damage = next(event.amount for event in ui.feedback
                                  if event.kind == "damage" and event.actor_id == actor and event.target_id == "enemy_0")
                    observed.add(damage)
                    with self.subTest(difficulty=difficulty, action=action, seed=seed):
                        self.assertEqual(result, CombatResult.VICTORY)
                        self.assertLessEqual(forecast.damage_min, damage)
                        self.assertGreaterEqual(forecast.damage_max, damage)
                self.assertEqual(min(observed), forecast.damage_min)
                self.assertEqual(max(observed), forecast.damage_max)

    def test_companion_previews_ignore_armor_guard_and_weapon_resistance(self):
        for action, expected in (("mara", (5, 7)), ("tobin", (4, 6))):
            for difficulty in CombatDifficulty:
                _, _, ui, _ = self.run_one(action, difficulty=difficulty, statuses={"guarded": 1, "vulnerable": 1})
                view = next(view for view in ui.snapshots[0].actions if view.id == action)
                self.assertEqual((view.damage_min, view.damage_max), expected)
                self.assertNotIn("Bleeding damage", view.description, "future ticks are not immediate command damage")

    def test_scout_preview_bypasses_defenses_without_spending_vulnerability(self):
        _, _, ui, _ = self.run_one("origin", origin=1, difficulty=CombatDifficulty.HARD,
                                  statuses={"guarded": 1, "vulnerable": 1})
        origin = next(view for view in ui.snapshots[0].actions if view.id == "origin")
        self.assertEqual((origin.damage_min, origin.damage_max), (7, 9))
        self.assertEqual({effect.id for effect in ui.snapshots[0].enemies[0].statuses}, {"guarded", "vulnerable"})

    def test_counter_preview_is_conditional_and_does_not_promise_selected_target(self):
        for intent, expected in (("guard", 0), ("strike", 4)):
            _, _, ui, _ = self.run_one("origin", intent=intent)
            origin = next(view for view in ui.snapshots[0].actions if view.id == "origin")
            self.assertEqual((origin.damage_min, origin.damage_max), (0, 4))
            self.assertTrue(origin.damage_conditional)
            self.assertIn("if a hit lands and you survive", origin.description)
            self.assertNotIn("damage to Chain Hunter", origin.description)
            counter = sum(event.amount for event in ui.feedback if event.kind == "damage" and event.actor_id == "player")
            self.assertEqual(counter, expected)

    def test_evasion_preserves_counter_without_promising_damage_this_turn(self):
        _, _, ui, _ = self.run_one("origin", intent="strike", player_statuses={"evade": 1})
        origin = next(view for view in ui.snapshots[0].actions if view.id == "origin")
        self.assertTrue(origin.damage_conditional)
        self.assertFalse(any(event.kind == "damage" and event.actor_id == "player" for event in ui.feedback))
        self.assertIn("riposte", {status.id for status in ui.snapshots[-1].player.statuses})

    def test_healer_and_defensive_commands_have_no_outgoing_hit_forecast(self):
        _, _, ui, _ = self.run_one("origin", origin=2)
        for action in ui.snapshots[0].actions:
            if action.id in {"origin", "defend", "item", "inspect", "flee"}:
                self.assertIsNone(action.damage_min)
                self.assertIsNone(action.damage_max)

    def test_survival_objective_has_no_damage_previews_or_counter_promise(self):
        for origin in range(3):
            _, enemy, ui, result = self.run_one("defend", origin=origin, intent="heavy", config=CombatConfig(
                objective="Hold the seal", objective_enemy_invulnerable=True,
                max_rounds=1, mara_aid=True, tobin_aid=True,
            ))
            self.assertEqual(result, CombatResult.VICTORY)
            self.assertEqual(enemy.hp, enemy.max_hp)
            self.assertTrue(all(action.damage_min is None and action.damage_max is None for action in ui.snapshots[0].actions))

    def test_free_target_inspection_and_repeated_snapshots_preserve_rng_and_live_state(self):
        state = self.state()
        enemies = [self.target(armor=1, archetype="regular"), self.target(armor=4)]
        enemies[1].name = "Iron Captain"
        ui = PreviewUI(["inspect", CombatCommand("target", "enemy_1"), "inspect", "attack"])
        rng = random.Random(39)
        engine = CombatEngine(ui, rng, CombatDifficulty.HARD)
        observations = []

        def setup():
            enemies[0].statuses.update({"guarded": 1, "vulnerable": 1})
            engine._player_statuses["ward"] = 2

        ui.on_begin = setup
        ui.before_action = lambda: observations.append((rng.getstate(), deepcopy(state.to_dict()),
                                                         deepcopy([enemy.__dict__ for enemy in enemies]),
                                                         dict(engine._player_statuses)))
        engine.run(state, enemies, CombatConfig(max_rounds=1))
        self.assertEqual(len(observations), 4)
        self.assertTrue(all(observation == observations[0] for observation in observations))
        first = next(action for action in ui.snapshots[0].actions if action.id == "attack")
        last = next(action for action in ui.snapshots[3].actions if action.id == "attack")
        self.assertEqual((first.damage_min, first.damage_max), (3, 5))
        self.assertEqual((last.damage_min, last.damage_max), (1, 1))
        self.assertIn("Iron Captain", last.description)
        expected_rng = random.Random(39)
        expected_rng.randint(1, 3)  # The one committed weapon hit.
        self.assertEqual(rng.getstate(), expected_rng.getstate(), "setup intents and free actions must not draw randomness")

    def test_shadow_inspection_discloses_weapon_only_resistance_separately_from_armor(self):
        for archetype, resistance in (("skirmisher", 1), ("boss", 2)):
            ui = PreviewUI(["inspect", "defend"])
            enemy = self.target(archetype=archetype)
            engine = CombatEngine(ui, random.Random(0), CombatDifficulty.HARD)
            engine.run(self.state(), [enemy], CombatConfig(max_rounds=1))
            self.assertEqual(ui.snapshots[0].enemies[0].armor, 3)
            self.assertEqual(ui.snapshots[0].enemies[0].weapon_resistance, resistance)
            text = " ".join(section["text"] for section in ui.panels[0][1]["sections"])
            self.assertIn(f"Shadow resistance {resistance}", text)
            self.assertIn("reduces weapon damage", text)
            self.assertIn("companions, Flanking Strike, and counters bypass", text)
            self.assertIn(f"Shadow resistance {resistance}", "\n".join(ui.output))

    def test_execution_inspection_offers_defend_after_focus_and_ability_are_spent(self):
        # Ordinary actions produce this state; no test hook injects exhaustion.
        state = self.state()
        enemy = ghorak()
        ui = PreviewUI(["power", "power", "origin", "item", "inspect", "defend"])
        result = CombatEngine(ui, random.Random(9)).run(state, [enemy], CombatConfig(max_rounds=5))

        before_inspect, after_inspect = ui.snapshots[4:6]
        self.assertEqual((before_inspect.round_number, before_inspect.player.focus), (5, 0))
        actions = {action.id: action for action in before_inspect.actions}
        self.assertEqual(actions["power"].disabled_reason, "Requires 1 Focus")
        self.assertEqual(actions["origin"].disabled_reason, "Already used in this battle")
        self.assertNotIn("mara", actions)
        self.assertTrue(actions["defend"].enabled)
        self.assertEqual(before_inspect.enemies[0].intent_id, "execution")
        self.assertIn("Defend or interrupt it", before_inspect.enemies[0].telegraph)
        self.assertEqual(after_inspect, before_inspect, "Inspect must leave the actual tactical choice intact")
        inspection = " ".join(section["text"] for section in ui.panels[0][1]["sections"])
        self.assertIn("defend or interrupt it", inspection.casefold())
        self.assertIn("Defend or interrupt it", "\n".join(ui.output))
        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual((state.character.hp, enemy.hp), (13, 2))

    def test_shadow_counter_bypasses_actual_armor_and_resistance_as_inspection_explains(self):
        state = self.state()
        enemy = chain_troll()
        ui = PreviewUI(["inspect", "origin"])
        result = CombatEngine(ui, random.Random(9), CombatDifficulty.HARD).run(
            state, [enemy], CombatConfig(max_rounds=1))

        initial = ui.snapshots[0]
        self.assertEqual((initial.enemies[0].armor, initial.enemies[0].weapon_resistance), (3, 2))
        forecast = next(action for action in initial.actions if action.id == "origin")
        self.assertEqual((forecast.damage_min, forecast.damage_max, forecast.damage_conditional), (0, 4, True))
        counters = [event.amount for event in ui.feedback if event.text == "Counterattack"]
        self.assertEqual(counters, [4])
        self.assertEqual(enemy.hp, 26)
        self.assertEqual(result, CombatResult.VICTORY)
        inspection = " ".join(section["text"] for section in ui.panels[0][1]["sections"])
        self.assertIn("companions, Flanking Strike, and counters bypass it", inspection)
        self.assertIn("counters bypass it", "\n".join(ui.output))

    def test_story_and_ranger_inspection_do_not_invent_shadow_resistance(self):
        for difficulty in (CombatDifficulty.STORY, CombatDifficulty.NORMAL):
            ui = PreviewUI(["inspect", "defend"])
            CombatEngine(ui, random.Random(0), difficulty).run(self.state(), [self.target()], CombatConfig(max_rounds=1))
            self.assertEqual(ui.snapshots[0].enemies[0].weapon_resistance, 0)
            self.assertNotIn("Shadow resistance", "\n".join(ui.output))

    def test_objective_success_plays_the_same_victory_cue_as_a_kill(self):
        _, _, ui, result = self.run_one("defend", config=CombatConfig(max_rounds=1, objective_enemy_invulnerable=True))
        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual(ui.sounds, ["danger", "victory"])
        state = self.state()
        enemy = Enemy("Practice", 1, 1, 1, 1)
        killed = PreviewUI(["attack"])
        CombatEngine(killed, random.Random(0)).run(state, [enemy])
        self.assertEqual(killed.sounds, ui.sounds)

    def test_failed_objective_and_escape_do_not_play_victory(self):
        ui = PreviewUI(["defend"])
        state = self.state()
        state.character.hp = 1
        CombatEngine(ui, random.Random(0)).run(state, [self.target(intent="execution")], CombatConfig(
            max_rounds=1, objective_enemy_invulnerable=True,
        ))
        self.assertEqual(ui.sounds, ["danger"])
        escaped = PreviewUI(["flee"])
        result = CombatEngine(escaped, random.Random(5)).run(self.state(1), [self.target()], CombatConfig(allow_flee=True))
        self.assertEqual(result, CombatResult.ESCAPED)
        self.assertEqual(escaped.sounds, ["danger"])

    def test_remedy_choices_show_actual_capped_healing_and_origin_bonus(self):
        for origin, missing, expected in ((0, 15, 9), (2, 15, 11), (0, 2, 2), (2, 2, 2)):
            with self.subTest(origin=origin, missing=missing):
                state = self.state(origin)
                state.character.hp -= missing
                ui = PreviewUI()
                engine = CombatEngine(ui, random.Random(0))
                before = state.character.hp
                self.assertTrue(engine.use_item(state))
                self.assertIn(f"+{expected} Health", ui.item_options[0][0])
                self.assertEqual(state.character.hp - before, expected)

    def test_full_health_bleeding_remedy_shows_cure_without_promising_healing(self):
        state = self.state()
        ui = PreviewUI()
        engine = CombatEngine(ui, random.Random(0))
        engine._player_statuses["bleeding"] = 2
        self.assertTrue(engine.use_item(state))
        self.assertIn("+0 Health, stops Bleeding", ui.item_options[0][0])
        self.assertEqual(state.character.hp, state.character.max_hp)
        self.assertNotIn("bleeding", engine._player_statuses)
        self.assertNotIn("healing_herb", state.character.inventory)

    def test_cancelling_previewed_remedy_preserves_item_statuses_and_rng(self):
        state = self.state(2)
        state.character.hp -= 3
        ui = PreviewUI(item_choice=None)
        rng = random.Random(3)
        engine = CombatEngine(ui, rng)
        engine._player_statuses["bleeding"] = 2
        before = deepcopy(state.to_dict()), dict(engine._player_statuses), rng.getstate()
        self.assertFalse(engine.use_item(state))
        self.assertIn("+3 Health, stops Bleeding", ui.item_options[0][0])
        self.assertEqual((state.to_dict(), engine._player_statuses, rng.getstate()), before)


if __name__ == "__main__":
    unittest.main()
