import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI
from tests.helpers import EpisodePlayer, VictoryCombat


class OpeningRouteTests(unittest.TestCase):
    EXPECTED_FLAGS = {
        1: "stood_with_mara",
        2: "pendant_hidden",
        3: "found_ranger_cipher",
        4: "returned_for_mara",
        5: "calenor_may_live",
    }

    def test_all_five_opening_choices_reach_final_cliffhanger(self) -> None:
        expected_art = {
            "A sturdy Bree traveler waits beneath a hedge gate with an ash staff.",
            "A hooded North-road scout studies tracks beside the road.",
            "A healer's apprentice kneels beside an open field kit with herbs and an ash staff.",
            "Calenor teaches a younger traveler to read trail signs beside a campfire.",
            "The wounded messenger Edrin offers a sealed letter and broken silver star.",
            "Mara throws back her cloak and draws two short blades.",
            "You and Mara stand back-to-back against the Orc attackers.",
            "You hide the broken silver star beneath a split hearthstone as Orc boots approach.",
            "An oak-leaf Ranger token and black arrowhead lie beside the fallen Edrin.",
            "Broken crockery leads toward an open rain door and the stable wall beyond.",
            "The scarred Orc captain raises a fist and stills every blade in the inn.",
            "Calenor's rain-stained letter bears an eight-pointed star and a road leading north.",
            "Tobin Reed stands rain-soaked in the wrecked inn, clutching his watch badge.",
            "Edrin's attic room holds muddy tracks, an untouched bed, a candle, and a blood-pink basin.",
            "A sword, healing herbs, and a smoke flask wait on the Prancing Pony pantry table.",
            "Mara cleans her twin knives beside dying embers, a shackle scar visible at her wrist.",
            "Calenor's hidden cache holds a folded Ranger cloak, a map, and a sealed note.",
            "Calenor's trail marks appear beneath a root beside a pale turned stone and red thread.",
            "Orc boots, a huge paw print, and a prisoner's dragging foot cross the muddy road.",
            "Three travelers hide in a flooded ditch while a mounted shadow passes overhead.",
            "A Ranger approaches a child beneath a starless sky as a North Downs house burns.",
            "Wounded Ned extends the missing silver ray toward the broken star-key.",
            "A leaf-shaped sword rests on a stone table in the flooded wayhouse armory.",
            "A floor mosaic shows silver roads and one black route ending at a split crown.",
        }
        seen: set[str] = set()

        for opening_choice, expected_flag in self.EXPECTED_FLAGS.items():
            with self.subTest(opening_choice=opening_choice), tempfile.TemporaryDirectory() as temporary:
                player = EpisodePlayer(
                    opening_choice=opening_choice,
                    origin_choice=((opening_choice - 1) % 3) + 1,
                    road_choice=((opening_choice - 1) % 3) + 1,
                    midgewater_topic=1 if opening_choice == 1 else 2,
                )
                ui = TerminalUI(
                    color=False,
                    fast=True,
                    screen_reader=True,
                    input_fn=player.read,
                    output_fn=player.write,
                )
                game = Game(
                    ui,
                    saves=SaveManager(Path(temporary)),
                    rng=random.Random(50 + opening_choice),
                )
                combat = VictoryCombat()
                game.combat = combat
                game.run()

                seen.update(
                    line[8:-1]
                    for line in player.output
                    if line.startswith("[Scene: ") and line.endswith("]")
                )
                self.assertTrue(game.state.flags[expected_flag])
                self.assertTrue(game.state.flags["part_one_complete"])
                self.assertTrue(game.state.flags["defeated_ghorak"])
                self.assertEqual(len(combat.encounters), 3)

        self.assertEqual(expected_art, seen & expected_art)

    def test_each_origin_has_a_complete_viable_route(self) -> None:
        for origin_choice in (1, 2, 3):
            with self.subTest(origin=origin_choice), tempfile.TemporaryDirectory() as temporary:
                player = EpisodePlayer(origin_choice=origin_choice)
                ui = TerminalUI(color=False, fast=True, input_fn=player.read, output_fn=player.write)
                game = Game(ui, saves=SaveManager(Path(temporary)), rng=random.Random(100 + origin_choice))
                game.combat = VictoryCombat()
                game.run()

                self.assertTrue(game.state.flags["part_one_complete"])
                self.assertTrue(game.state.flags["ned_stabilized"])

    def test_discoveries_unlock_hidden_road_instead_of_obsolete_early_exit(self) -> None:
        state, transcript = self._resolve_cliffhanger(
            hope=4,
            corruption=0,
            mara_trust=3,
            tobin_trust=3,
            flags={
                "defeated_ghorak": True,
                "ned_survived": True,
                "learned_dead_road_map": True,
                "found_ranger_cipher": True,
            },
        )

        self.assertEqual(state.ending, "hidden_road")
        self.assertTrue(state.flags["part_two_hidden_route_known"])
        self.assertIn("unmarked stair opens beneath the broken crown", transcript)
        self.assertIn("archive clues revealed a hidden descent", transcript)

    def test_companion_bonds_and_ned_rescue_create_fellowship_ending(self) -> None:
        state, transcript = self._resolve_cliffhanger(
            hope=4,
            corruption=1,
            mara_trust=2,
            tobin_trust=2,
            flags={"defeated_ghorak": True, "ned_survived": True},
        )

        self.assertEqual(state.ending, "fellowship")
        self.assertTrue(state.flags["part_two_ned_safe"])
        self.assertIn("Ned lives, and Tobin follows", transcript)
        self.assertIn("She follows by choice", transcript)

    def test_broken_trust_and_neds_death_create_keeper_ending(self) -> None:
        state, transcript = self._resolve_cliffhanger(
            hope=3,
            corruption=1,
            mara_trust=-2,
            tobin_trust=0,
            flags={"defeated_ghorak": True, "ned_survived": False},
        )

        self.assertEqual(state.ending, "keeper_of_secrets")
        self.assertFalse(state.flags["part_two_ned_safe"])
        self.assertIn("Ned fell", transcript)
        self.assertIn("no longer trusts", transcript)

    def test_repeated_use_of_star_power_can_claim_an_otherwise_victorious_route(self) -> None:
        state, transcript = self._resolve_cliffhanger(
            hope=0,
            corruption=2,
            mara_trust=3,
            tobin_trust=3,
            flags={
                "defeated_ghorak": True,
                "ned_survived": True,
                "accepted_star_power": True,
                "used_star_in_final": True,
            },
        )

        self.assertEqual(state.ending, "shadow_claim")
        self.assertIn("star found a foothold", transcript)

    @staticmethod
    def _resolve_cliffhanger(
        *,
        hope: int,
        corruption: int,
        mara_trust: int,
        tobin_trust: int,
        flags: dict[str, bool],
    ) -> tuple[GameState, str]:
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: "2", output_fn=output.append)
        game = Game(ui, rng=random.Random(9))
        character = Character.from_origin("Arin", ORIGINS[0])
        character.hope = hope
        character.corruption = corruption
        character.mara_trust = mara_trust
        character.tobin_trust = tobin_trust
        game.state = GameState(character, scene="cliffhanger", flags=dict(flags))

        game._cliffhanger()
        game._show_ending()
        return game.state, "\n".join(output)


if __name__ == "__main__":
    unittest.main()
