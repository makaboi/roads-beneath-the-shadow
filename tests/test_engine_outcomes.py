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
    def test_shadow_marked_ending_does_not_claim_a_fully_healed_traveler_is_wounded(self):
        game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
        character = Character.from_origin("Arin", ORIGINS[0])
        character.corruption = 3
        game.state = GameState(character, scene="cliffhanger")

        game._cliffhanger()

        self.assertEqual(game.state.ending, "shadow_claim")
        self.assertEqual(character.hp, character.max_hp)
        title, prose = game._ending_copy()
        self.assertEqual(title, "SHADOW-MARKED")
        self.assertIn("You descend as the Black Rider", prose)
        self.assertNotIn("wounded", prose)

    def test_using_the_last_herb_in_inventory_refreshes_neds_rescue_routes_and_costs(self):
        for origin in (0, 1):
            for confirm_rescue in (False, True):
                with self.subTest(origin=origin, confirm_rescue=confirm_rescue):
                    menus = []
                    inventory = []

                    class RescueUtilityUI(TerminalUI):
                        def __init__(self):
                            super().__init__(color=False, fast=True, output_fn=lambda _: None)
                            self.actions = iter(({"action": "use", "item_id": "healing_herb"}, {"action": "close"}))

                        def choose_story(self, heading, options):
                            if heading == "HOW DO YOU REACH NED?":
                                # The actual rush costs two Health, creating a
                                # legitimate opportunity to consume the herb.
                                return 4
                            self.assert_heading(heading)
                            menus.append(tuple(options))
                            return "i" if len(menus) == 1 else 1 if confirm_rescue else None

                        @staticmethod
                        def assert_heading(heading):
                            if heading != "NED IS FADING":
                                raise AssertionError(f"Unexpected story decision: {heading}")

                        def show_panel(self, kind, data):
                            if kind != "inventory":
                                raise AssertionError(f"Unexpected panel: {kind}")
                            inventory.append(data)
                            return next(self.actions)

                    game = Game(RescueUtilityUI())
                    game.state = GameState(Character.from_origin("Arin", ORIGINS[origin]), scene="missing_watchman")
                    rng_before = game.combat.rng.getstate()

                    self.assertEqual(game._missing_watchman(), confirm_rescue)

                    self.assertTrue(any("Healing Herb" in option for option in menus[0]))
                    self.assertFalse(any("Healing Herb" in option for option in menus[1]))
                    self.assertTrue(menus[1][0].startswith("Free him now"))
                    self.assertTrue(any(item["id"] == "healing_herb" and item["count"] == 1 for item in inventory[0]["items"]))
                    self.assertFalse(any(item["id"] == "healing_herb" for item in inventory[1]["items"]))
                    character = game.state.character
                    self.assertNotIn("healing_herb", character.inventory)
                    self.assertEqual(character.hp, character.max_hp)
                    self.assertTrue(game.state.flags["rushed_causeway"])
                    self.assertTrue(game.state.flags["missing_watchman_approach_chosen"])
                    self.assertFalse(game.state.flags.get("ned_stabilized", False))
                    self.assertEqual(game.state.flags.get("ned_freed_before_combat", False), confirm_rescue)
                    self.assertEqual(character.tobin_trust, 1 if confirm_rescue else 0)
                    self.assertEqual((character.hope, character.corruption), (0, 0))
                    self.assertEqual(game.state.play_minutes, 6 if confirm_rescue else 0)
                    self.assertEqual(game.state.scene, "marsh_ambush" if confirm_rescue else "missing_watchman")
                    self.assertEqual(game.combat.rng.getstate(), rng_before)

    def test_fellowship_copy_does_not_claim_tobin_descends_when_he_returns_with_ned(self):
        output = []
        game = Game(TerminalUI(color=False, fast=True, output_fn=output.append))
        character = Character.from_origin("Arin", ORIGINS[0])
        character.mara_trust = 1
        character.tobin_trust = 1
        game.state = GameState(character, scene="cliffhanger", flags={"ned_survived": True})

        game._cliffhanger()

        self.assertEqual(game.state.ending, "fellowship")
        self.assertTrue(game.state.flags["tobin_returns_with_ned"])
        self.assertFalse(game.state.flags["part_two_tobin_present"])
        self.assertIn("see him home", " ".join(output))
        self.assertNotIn("Tobin", game._ending_copy()[1])

    def test_real_marsh_outcomes_keep_ned_and_the_recovered_shard_consistent(self):
        for victory, stabilized in ((True, False), (False, True), (False, False)):
            with self.subTest(victory=victory, stabilized=stabilized):
                output = []
                ui = TerminalUI(color=False, fast=True, output_fn=output.append)
                action = "Attack" if victory else "Defend"
                ui.choose = lambda _title, options, **_: next(i + 1 for i, option in enumerate(options) if option.startswith(action))
                game = Game(ui, rng=random.Random(12), difficulty=CombatDifficulty.STORY if victory else CombatDifficulty.HARD)
                character = Character.from_origin("Arin", ORIGINS[0])
                character.hp = character.max_hp if victory else 1
                # Trust disables aid, rather than removing either companion
                # from this scene, so the battle outcome is deterministic.
                character.mara_trust = character.tobin_trust = -1
                character.add_item("silver_star")
                game.state = GameState(character, scene="marsh_ambush", flags={"ned_stabilized": stabilized})
                outcomes = []
                run = game.combat.run

                def combat(*args):
                    outcomes.append(run(*args))
                    return outcomes[-1]

                game.combat.run = combat
                self.assertTrue(game._marsh_ambush())
                self.assertEqual(outcomes, [CombatResult.VICTORY if victory else CombatResult.DEFEAT])
                self.assertEqual(game.state.scene, "wayhouse")
                self.assertEqual(game.state.flags["ned_survived"], victory or stabilized)
                self.assertEqual(character.inventory["star_key"], 1)
                self.assertNotIn("silver_star", character.inventory)
                prose = " ".join(" ".join(output).split())
                if victory:
                    self.assertIn("Ned cuts a silver point", prose)
                    self.assertNotIn("a breath that does not come", prose)
                elif stabilized:
                    self.assertIn("The bindings you set have held", prose)
                    self.assertIn("Ned opens his hand", prose)
                    self.assertNotIn("a breath that does not come", prose)
                else:
                    self.assertIn("a breath that does not come", prose)
                    self.assertIn("draws the missing silver ray from inside his friend's coat", prose)
                    self.assertIn("Tobin keeps Ned's broken lantern", prose)
                    self.assertNotIn("Ned opens his hand", prose)
                    self.assertNotIn("Ned cuts a silver point", prose)
                self.assertIn("Ned survived" if victory or stabilized else "Ned died", game.state.journal[-1])

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
