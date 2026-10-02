"""Combat outcomes retain the round and story consequence that actually occurred."""

import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import CombatConfig, CombatDifficulty, CombatEngine, CombatResult
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.profile import ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI
from tests.test_combat_turns import CombatViewUI


class EngineOutcomeTests(unittest.TestCase):
    def test_defeat_and_counterattack_victory_report_the_round_that_finished(self):
        for action, hp, enemy_hp, phase in (
            ("attack", 1, 100, "defeat"),
            ("origin", 28, 1, "victory"),
        ):
            with self.subTest(phase=phase):
                ui = CombatViewUI([action])
                state = GameState(Character.from_origin("Arin", ORIGINS[0]))
                state.character.hp = hp
                enemy = Enemy("Hunter", enemy_hp, enemy_hp, 4, 4)
                result = CombatEngine(ui, random.Random(1)).run(state, [enemy])
                self.assertEqual(result.value, phase)
                self.assertEqual((ui.snapshots[-1].phase, ui.snapshots[-1].round_number), (phase, 1))

    def test_surviving_six_rounds_does_not_claim_to_kill_ghorak(self):
        with tempfile.TemporaryDirectory() as directory:
            output = []
            ui = TerminalUI(color=False, fast=True, output_fn=output.append)
            ui.choose = lambda _title, options, **_: next(i + 1 for i, option in enumerate(options) if option.startswith("Defend"))
            root = Path(directory)
            game = Game(ui, saves=SaveManager(root), profile=ProfileManager(root / "profile.json"), rng=random.Random(12), difficulty=CombatDifficulty.STORY)
            game._story_choice = lambda *_: 2
            game.state = GameState(Character.from_origin("Arin", ORIGINS[0]), scene="final_battle")
            captured = {}
            run = game.combat.run

            def combat(state, enemies, config):
                captured["enemies"] = enemies
                captured["result"] = run(state, enemies, config)
                return captured["result"]

            game.combat.run = combat
            self.assertTrue(game._final_battle())
            self.assertEqual(captured["result"], CombatResult.VICTORY)
            self.assertTrue(all(enemy.alive for enemy in captured["enemies"]))
            self.assertTrue(game.state.flags["escaped_ghorak_collapse"])
            self.assertFalse(game.state.flags.get("defeated_ghorak", False))
            self.assertFalse(game.state.flags.get("defeated_by_ghorak", False))
            self.assertNotEqual(game._determine_ending(), "shadow_claim")
            self.assertIn("alive, cut off", " ".join(output))
            self.assertNotIn("Ghorak falls", " ".join(output))

            game.state.flags["part_two_hidden_route_known"] = False
            game.saves.save(1, game.state)
            game.state = game.saves.load(1)
            recap = dict(game._ending_breakdown())["Final stand"]
            self.assertIn("survived the collapsing wayhouse", recap)
            self.assertNotIn("Ghorak was defeated", recap)

    def test_actual_kill_keeps_defeated_ghorak_consequence(self):
        output = []
        ui = TerminalUI(color=False, fast=True, output_fn=output.append)
        ui.choose = lambda _title, _options, **_: 1
        game = Game(ui, rng=random.Random(12), difficulty=CombatDifficulty.STORY)
        game._story_choice = lambda *_: 2
        character = Character.from_origin("Arin", ORIGINS[1])
        # The Scout's pillar tactic removes the guard and grants an opening.
        game.state = GameState(character, scene="final_battle")
        self.assertTrue(game._final_battle())
        self.assertTrue(game.state.flags["defeated_ghorak"])
        self.assertFalse(game.state.flags.get("escaped_ghorak_collapse", False))
        self.assertIn("Ghorak falls", " ".join(output))
        game.state.flags["part_two_hidden_route_known"] = False
        self.assertIn("Ghorak was defeated", dict(game._ending_breakdown())["Final stand"])

    def test_invalid_item_and_target_adapter_answers_spend_no_turn_or_supplies(self):
        for invalid in (0, -1, 99, True, "1"):
            with self.subTest(answer=invalid):
                class InvalidMenuUI(CombatViewUI):
                    def choose(self, title, options, *, allow_back=False):
                        if title in {"Choose a target", "Use which item?"}:
                            return invalid
                        return super().choose(title, options, allow_back=allow_back)

                ui = InvalidMenuUI(["target", "item", "defend"])
                state = GameState(Character.from_origin("Arin", ORIGINS[0]))
                state.character.hp -= 2
                supplies = dict(state.character.inventory)
                enemies = [Enemy("One", 100, 100, 1, 1), Enemy("Two", 100, 100, 1, 1)]
                CombatEngine(ui, random.Random(2)).run(state, enemies, CombatConfig(max_rounds=1))
                self.assertEqual(state.character.inventory, supplies)
                self.assertEqual([snapshot.round_number for snapshot in ui.snapshots], [1, 1, 1, 1])
                self.assertTrue(all(snapshot.target_id == "enemy_0" for snapshot in ui.snapshots))
                self.assertEqual([enemy.turn_count for enemy in enemies], [1, 1])

    def test_remembered_arrivals_do_not_count_as_two_bree_investigations(self):
        output = []
        game = Game(TerminalUI(color=False, fast=True, output_fn=output.append))
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="bree_exploration",
            flags={"bree_map_seen": True},
            visited=["chapter1_intro", "chapter1_decision", "branch_fight", "aftermath", "bree_exploration"],
        )
        choices = iter((5, None))
        game._story_choice = lambda *_: next(choices)
        self.assertFalse(game._bree_exploration())
        self.assertEqual(game.state.scene, "bree_exploration")
        self.assertIn("Investigate at least two places", " ".join(output))

        game.state.visit("messenger_room")
        game.state.visit("stable_yard")
        game._story_choice = lambda *_: 3
        self.assertTrue(game._bree_exploration())
        self.assertEqual(game.state.scene, "north_gate")


if __name__ == "__main__":
    unittest.main()
