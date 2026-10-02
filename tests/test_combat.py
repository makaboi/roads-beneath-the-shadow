import random
import unittest
from collections.abc import Callable, Sequence

from roads_beneath_shadow.combat import (
    CombatConfig,
    CombatDifficulty,
    CombatEngine,
    CombatResult,
    ash_archer,
    ash_commander,
    ash_sapper,
    black_rider_echo,
    chain_troll,
    ghorak,
    orc_scout,
    teren_false_ranger,
)
from roads_beneath_shadow.content import ITEMS, ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.ui import TerminalUI


class PolicyUI(TerminalUI):
    """Test UI that lets a deterministic policy inspect the offered choices."""

    def __init__(self, selector: Callable[[str, Sequence[str]], int | None]) -> None:
        self.output: list[str] = []
        self._selector = selector
        super().__init__(color=False, fast=True, output_fn=self.output.append)

    def choose(self, title: str, options: Sequence[str], *, allow_back: bool = False) -> int | None:
        return self._selector(title, options)


class CombatTests(unittest.TestCase):
    @staticmethod
    def _ui(answers: list[str]) -> tuple[TerminalUI, list[str]]:
        choices = iter(answers)
        output: list[str] = []
        return TerminalUI(color=False, fast=True, input_fn=lambda _: next(choices), output_fn=output.append), output

    def test_part_two_enemy_factories_return_fresh_tactical_archetypes(self) -> None:
        first = chain_troll()
        second = chain_troll()
        self.assertIsNot(first, second)
        self.assertEqual((first.max_hp, first.armor), (30, 3))
        self.assertEqual(first.intent_pattern, ("guard", "heavy", "cleave"))
        self.assertEqual(first.phase_two_pattern, ("execution", "menace", "heavy"))
        self.assertEqual(first.phase_threshold, 0.5)

        rider = black_rider_echo(final=True)
        self.assertEqual(rider.max_hp, 999)
        self.assertEqual(rider.intent_pattern, ("menace", "heavy", "quick"))
        self.assertEqual(rider.phase_two_pattern, ("menace", "execution", "cleave"))

        formation = (ash_sapper(), ash_commander(), ash_archer(), teren_false_ranger())
        self.assertEqual(
            [enemy.archetype for enemy in formation],
            ["saboteur", "commander", "archer", "duelist"],
        )

    def test_attack_can_win_encounter(self) -> None:
        answers = iter(["1"])
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=output.append)
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        enemy = Enemy("Practice Orc", 1, 1, 1, 1)

        result = CombatEngine(ui, random.Random(4)).run(state, [enemy])

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertTrue(state.character.alive)
        self.assertEqual(enemy.hp, 0)

    def test_healing_item_recovers_health(self) -> None:
        answers = iter(["1"])
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=output.append)
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        state.character.hp = 5
        engine = CombatEngine(ui, random.Random(1))

        consumed_turn = engine.use_item(state)

        self.assertTrue(consumed_turn)
        self.assertEqual(state.character.hp, 14)
        self.assertNotIn("healing_herb", state.character.inventory)

    def test_player_can_change_target_without_spending_turn(self) -> None:
        answers = iter(["6", "2", "1", "1"])
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=output.append)
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        first = Enemy("First Orc", 1, 1, 1, 1)
        second = Enemy("Second Orc", 1, 1, 1, 1)

        result = CombatEngine(ui, random.Random(2)).run(state, [first, second])

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertTrue(any("attention to Second Orc" in line for line in output))

    def test_every_living_enemy_executes_its_telegraphed_intent(self) -> None:
        ui, output = self._ui(["1"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        first = Enemy("First Orc", 40, 40, 1, 1)
        second = Enemy("Second Orc", 40, 40, 1, 1)

        result = CombatEngine(ui, random.Random(9)).run(
            state,
            [first, second],
            CombatConfig(max_rounds=1),
        )

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual(state.character.hp, state.character.max_hp - 2)
        self.assertTrue(any("First Orc's Strike hits" in line for line in output))
        self.assertTrue(any("Second Orc's Strike hits" in line for line in output))

    def test_power_attack_interrupts_telegraphed_move_but_exposes_player(self) -> None:
        ui, output = self._ui(["2"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        enemy = Enemy("Crusher", 50, 50, 4, 4, intent_pattern=("heavy",))

        result = CombatEngine(ui, random.Random(3)).run(state, [enemy], CombatConfig(max_rounds=1))

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual(state.character.hp, state.character.max_hp)
        transcript = "\n".join(output)
        self.assertIn("interrupts its intent", transcript)
        self.assertIn("leaves you Exposed", transcript)
        self.assertIn("Heavy Blow is interrupted", transcript)

    def test_uninterrupted_enemy_exploits_power_attack_exposure(self) -> None:
        ui, output = self._ui(["2"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        enemy = Enemy("Knife Orc", 50, 50, 1, 1, intent_pattern=("strike",))

        CombatEngine(ui, random.Random(2)).run(state, [enemy], CombatConfig(max_rounds=1))

        self.assertEqual(state.character.hp, state.character.max_hp - 3)
        self.assertTrue(any("exploits your Exposed stance" in line for line in output))

    def test_scout_ability_bypasses_armor_and_evades_next_attack(self) -> None:
        ui, output = self._ui(["6"])
        state = GameState(Character.from_origin("Arin", ORIGINS[1]))
        enemy = Enemy("Iron Orc", 50, 50, 5, 5, armor=8)

        CombatEngine(ui, random.Random(1)).run(state, [enemy], CombatConfig(max_rounds=1))

        self.assertLess(enemy.hp, enemy.max_hp)
        self.assertEqual(state.character.hp, state.character.max_hp)
        self.assertEqual(enemy.statuses.get("vulnerable"), 1)
        self.assertTrue(any("FLANKING STRIKE" in line for line in output))
        self.assertTrue(any("evade" in line.lower() for line in output))

    def test_wayfarer_ability_guards_and_counterattacks(self) -> None:
        ui, output = self._ui(["6"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        enemy = Enemy("Road Orc", 50, 50, 3, 3)

        CombatEngine(ui, random.Random(1)).run(state, [enemy], CombatConfig(max_rounds=1))

        self.assertEqual(state.character.hp, state.character.max_hp - 1)
        self.assertEqual(enemy.hp, 46)
        self.assertTrue(any("STAND FAST" in line for line in output))
        self.assertTrue(any("counter" in line.lower() for line in output))

    def test_invulnerable_objective_offers_only_defensive_actions(self) -> None:
        offered: tuple[str, ...] = ()

        def select(title: str, options: Sequence[str]) -> int:
            nonlocal offered
            self.assertEqual(title, "Choose your action")
            offered = tuple(options)
            return 1

        ui = PolicyUI(select)
        state = GameState(Character.from_origin("Arin", ORIGINS[1]))
        enemy = Enemy("Objective Shade", 50, 50, 3, 3, intent_pattern=("strike",))

        result = CombatEngine(ui, random.Random(4)).run(
            state,
            [enemy],
            CombatConfig(
                max_rounds=1,
                surprise_round=True,
                mara_aid=True,
                tobin_aid=True,
                objective_enemy_invulnerable=True,
            ),
        )

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual(enemy.hp, enemy.max_hp)
        self.assertEqual(
            offered,
            (
                "Defend (halve physical hits, recover 1 Focus)",
                "Use an item",
                "Inspect enemy",
                "Mara: Crossing Guard (-1 Focus, defend)",
                "Tobin: Deflecting Shot (-1 Focus, defend)",
            ),
        )

    def test_healer_ability_restores_health_and_wards_damage(self) -> None:
        ui, output = self._ui(["6"])
        state = GameState(Character.from_origin("Arin", ORIGINS[2]))
        state.character.hp = 10
        enemy = Enemy("Needle Orc", 50, 50, 1, 1)

        CombatEngine(ui, random.Random(1)).run(state, [enemy], CombatConfig(max_rounds=1))

        self.assertEqual(state.character.hp, 18)
        self.assertTrue(any("FIELD REMEDY" in line for line in output))
        self.assertTrue(any("ward absorbs" in line for line in output))

    def test_ghorak_enters_a_telegraphed_second_phase(self) -> None:
        ui, output = self._ui(["1"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        boss = ghorak()
        boss.hp = 12

        CombatEngine(ui, random.Random(6)).run(state, [boss], CombatConfig(max_rounds=1))

        self.assertEqual(boss.phase, 2)
        transcript = "\n".join(output)
        self.assertIn("PHASE II", transcript)
        self.assertIn("Shadow Mark", transcript)

    def test_difficulty_changes_incoming_damage_deterministically(self) -> None:
        remaining_health: dict[CombatDifficulty, int] = {}
        for difficulty in CombatDifficulty:
            ui, _ = self._ui(["1"])
            state = GameState(Character.from_origin("Arin", ORIGINS[0]))
            enemy = Enemy("Measured Orc", 50, 50, 4, 4)
            CombatEngine(ui, random.Random(7)).run(
                state,
                [enemy],
                CombatConfig(max_rounds=1, difficulty=difficulty),
            )
            remaining_health[difficulty] = state.character.hp

        self.assertGreater(remaining_health[CombatDifficulty.STORY], remaining_health[CombatDifficulty.NORMAL])
        self.assertGreater(remaining_health[CombatDifficulty.NORMAL], remaining_health[CombatDifficulty.HARD])

    def test_shadow_opens_with_a_telegraphed_attack_and_two_focus_power_cost(self) -> None:
        ui, output = self._ui(["3"])
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))

        CombatEngine(ui, random.Random(4)).run(
            state,
            [ghorak()],
            CombatConfig(max_rounds=1, difficulty=CombatDifficulty.HARD),
        )

        transcript = "\n".join(output)
        self.assertIn("Shadow rules: enemies open aggressively; Power Attack costs 2 Focus.", transcript)
        self.assertIn("Power attack (-2 Focus, become Exposed)", transcript)
        self.assertIn("Ash Cleave", transcript)
        self.assertNotIn("war cry steels", transcript.lower())

    def test_fixed_seed_boss_band_is_story_then_ranger_then_shadow(self) -> None:
        """A repetitive damage race should not trivialize the top difficulty."""

        seeds = (0, 1, 2, 3, 5, 8, 13, 21)
        wins: dict[CombatDifficulty, int] = {}
        health: dict[CombatDifficulty, int] = {}

        for difficulty in CombatDifficulty:
            results = [self._run_simple_boss_policy(difficulty, seed) for seed in seeds]
            wins[difficulty] = sum(result is CombatResult.VICTORY for result, _ in results)
            health[difficulty] = sum(remaining for _, remaining in results)

        self.assertEqual(wins[CombatDifficulty.STORY], len(seeds))
        self.assertEqual(wins[CombatDifficulty.NORMAL], len(seeds))
        self.assertLessEqual(wins[CombatDifficulty.HARD], len(seeds) // 4)
        self.assertGreater(health[CombatDifficulty.STORY], health[CombatDifficulty.NORMAL])
        self.assertGreater(health[CombatDifficulty.NORMAL], health[CombatDifficulty.HARD])

    def test_every_origin_has_a_repeatable_tactical_shadow_boss_route(self) -> None:
        """Shadow punishes repetition, but telegraphs leave a reliable answer."""

        seeds = (0, 1, 2, 3, 5, 8, 13, 21)
        for origin in ORIGINS:
            for seed in seeds:
                with self.subTest(origin=origin.origin_id, seed=seed):
                    result, remaining = self._run_tactical_shadow_policy(origin.origin_id, seed)
                    self.assertEqual(result, CombatResult.VICTORY)
                    self.assertGreater(remaining, 0)

    @staticmethod
    def _equip(character: Character, *item_ids: str) -> None:
        for item_id in item_ids:
            character.add_item(item_id)
            character.equip(ITEMS[item_id])

    @classmethod
    def _run_simple_boss_policy(
        cls,
        difficulty: CombatDifficulty,
        seed: int,
    ) -> tuple[CombatResult, int]:
        character = Character.from_origin("Arin", ORIGINS[0])
        cls._equip(character, "bree_blade", "ranger_cloak")
        state = GameState(character)
        power_cost = 2 if difficulty is CombatDifficulty.HARD else 1

        def select(title: str, options: Sequence[str]) -> int:
            if title != "Choose your action":
                raise AssertionError(f"Unexpected policy prompt: {title}")
            return 2 if character.focus >= power_cost else 1

        ui = PolicyUI(select)
        result = CombatEngine(ui, random.Random(seed)).run(
            state,
            [ghorak(), orc_scout("Ash-hand Guard")],
            CombatConfig(difficulty=difficulty),
        )
        return result, character.hp

    @classmethod
    def _run_tactical_shadow_policy(cls, origin_id: str, seed: int) -> tuple[CombatResult, int]:
        origin = next(candidate for candidate in ORIGINS if candidate.origin_id == origin_id)
        character = Character.from_origin("Arin", origin)
        cls._equip(character, "numenorean_blade", "ranger_cloak")
        character.mara_trust = 2
        character.tobin_trust = 2
        state = GameState(character)
        boss = ghorak()
        guard = orc_scout("Ash-hand Guard")
        target = boss
        turns_taken = 0
        ability_used = False

        def option_number(options: Sequence[str], prefix: str) -> int:
            return next(index for index, label in enumerate(options, 1) if label.startswith(prefix))

        def commit(options: Sequence[str], prefix: str) -> int:
            nonlocal turns_taken
            turns_taken += 1
            return option_number(options, prefix)

        def select(title: str, options: Sequence[str]) -> int:
            nonlocal ability_used, target
            if title == "Choose a target":
                target = guard if guard.alive else boss
                return option_number(options, target.name)
            if title == "Use which item?":
                return 1
            if title != "Choose your action":
                raise AssertionError(f"Unexpected policy prompt: {title}")

            if not target.alive:
                target = boss
            if guard.alive and target is not guard:
                return option_number(options, "Change target")

            next_turn = turns_taken + 1
            if origin.ability_id == "stand_fast" and not ability_used and next_turn == 1:
                ability_used = True
                return commit(options, origin.ability_name)
            if origin.ability_id in {"flanking_strike", "field_remedy"} and next_turn == 1:
                return commit(options, "Defend")
            if origin.ability_id == "flanking_strike" and guard.alive and not ability_used:
                ability_used = True
                return commit(options, origin.ability_name)
            if (
                origin.ability_id == "field_remedy"
                and not ability_used
                and character.hp <= character.max_hp - 5
            ):
                ability_used = True
                return commit(options, origin.ability_name)

            has_herb = any(ITEMS[item_id].healing for item_id in character.inventory)
            if character.hp <= max(8, character.max_hp // 3) and has_herb:
                return commit(options, "Use an item")

            if target.current_intent in {"heavy", "execution", "pounce"}:
                action = "Power attack" if character.focus >= 2 else "Defend"
                return commit(options, action)
            if guard.alive:
                action = "Power attack" if character.focus >= 2 else "Attack"
                return commit(options, action)
            if target.current_intent == "menace" and character.focus >= 2:
                return commit(options, "Power attack")
            if target.current_intent in {"strike", "quick", "maul", "cleave"}:
                return commit(options, "Defend")
            return commit(options, "Attack")

        ui = PolicyUI(select)
        result = CombatEngine(ui, random.Random(seed)).run(
            state,
            [boss, guard],
            CombatConfig(
                difficulty=CombatDifficulty.HARD,
                mara_aid=True,
                tobin_aid=True,
            ),
        )
        return result, character.hp


if __name__ == "__main__":
    unittest.main()
