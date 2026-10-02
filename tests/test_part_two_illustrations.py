"""Story illustrations accompany their discoveries at the actual decision."""

import textwrap
import unittest

from roads_beneath_shadow import part_two_artwork as artwork
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.narrative import NarrativeDirector
from roads_beneath_shadow.part_two import PartTwoEpisode
from roads_beneath_shadow.pixel_ui import InputRequest, PixelUI


class PartTwoIllustrationTests(unittest.TestCase):
    def presented_decision(self, scene, *, mara_present, tobin_present, extra_flags=None, answers=()):
        ui = PixelUI(text_speed="instant")
        director = NarrativeDirector()
        decisions = []
        selections = iter((*answers, None))

        def choose(heading, options):
            while not ui.events.empty():
                event = ui.events.get_nowait()
                if event.kind in {"clear", "art", "title", "text"}:
                    director.feed(event)
            director.prepare(
                InputRequest(1, "choice", heading, tuple(options), story=True),
                wrap=lambda text: textwrap.wrap(text, width=90) or [""],
                rows=8,
            )
            decisions.append(heading)
            selected = next(selections)
            return next(index + 1 for index, option in enumerate(options) if selected in option) if selected else None

        state = GameState(
            Character.from_origin("Mira", ORIGINS[0]),
            scene=scene, chapter=2,
            flags={"part_two_mara_present": mara_present, "part_two_tobin_present": tobin_present, **(extra_flags or {})},
        )
        episode = PartTwoEpisode(ui, choose, lambda *_: self.fail("An unaccepted story decision must not start combat"))
        self.assertFalse(episode.run_scene(state))
        self.assertEqual(state.scene, scene)
        self.assertEqual(state.play_minutes, 0)
        return director, decisions

    def test_hall_does_not_reveal_unanswered_testimony_or_an_unearned_hidden_stair(self):
        for road_name in (False, True):
            with self.subTest(road_name=road_name):
                director, _ = self.presented_decision(
                    "part2_hall_exploration", mara_present=True, tobin_present=False,
                    extra_flags={"part2_spoke_road_name": road_name},
                )
                self.assertFalse(any(beat.scene_text in {
                    artwork.FIRST_WARDEN_TESTIMONY_ART, artwork.HIDDEN_WARDEN_STAIR_ART,
                } for beat in director.beats))

                director, _ = self.presented_decision(
                    "part2_hall_exploration", mara_present=True, tobin_present=False,
                    extra_flags={"part2_spoke_road_name": road_name}, answers=("Dead Testimony",),
                )
                self.assertEqual(director.pages[-1].scene_text == artwork.FIRST_WARDEN_TESTIMONY_ART, road_name)
                self.assertIn("We kept no crown" if road_name else "testimony remains unanswered", " ".join(director.pages[-1].text.split()))
                self.assertFalse(any(beat.scene_text == artwork.HIDDEN_WARDEN_STAIR_ART for beat in director.beats))

    def test_hidden_stair_illustration_accompanies_its_actual_earned_descent(self):
        for knows_route, approach in ((False, "exposed bridgehead"), (True, "exposed bridgehead"), (True, "hidden Warden stair")):
            with self.subTest(knows_route=knows_route, approach=approach):
                ui = PixelUI(text_speed="instant")
                director = NarrativeDirector()
                choices = iter((approach, "Defend the ropes"))

                def choose(_heading, options):
                    target = next(choices)
                    return next(index + 1 for index, option in enumerate(options) if target in option)

                def combat(_state, _enemies, _config):
                    from roads_beneath_shadow.combat import CombatResult

                    while not ui.events.empty():
                        event = ui.events.get_nowait()
                        if event.kind in {"clear", "art", "title", "text"}:
                            director.feed(event)
                    director.prepare(wrap=lambda text: textwrap.wrap(text, width=90) or [""], rows=8, cinematic=True)
                    return CombatResult.VICTORY

                state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="part2_echo_bridge", chapter=2,
                                  flags={"part_two_hidden_route_known": knows_route})
                self.assertTrue(PartTwoEpisode(ui, choose, combat).run_scene(state))
                stair_beats = [beat for beat in director.beats if beat.scene_text == artwork.HIDDEN_WARDEN_STAIR_ART]
                self.assertEqual(bool(stair_beats), approach == "hidden Warden stair")
                if stair_beats:
                    self.assertIn("The hidden stair passes a silver oath", stair_beats[0].text)
                    self.assertTrue(stair_beats[0].has_narration)
                    self.assertTrue(state.flags["part2_testimony_first"])

    def test_drowned_mile_choice_stays_with_the_flood_and_prison_cart(self):
        for mara in (False, True):
            for tobin in (False, True):
                with self.subTest(mara=mara, tobin=tobin):
                    director, decisions = self.presented_decision(
                        "part2_drowned_mile", mara_present=mara, tobin_present=tobin,
                    )
                    self.assertEqual(decisions, ["WHO DO YOU REACH FIRST?"])
                    self.assertEqual(director.pages[-1].scene_text, artwork.DROWNED_CARAVAN_ART)
                    self.assertIn("sluice horn", director.pages[-1].text)
                    self.assertIn("Two trails", director.pages[-1].text)
                    self.assertTrue(director.beats[-1].has_narration)
                    self.assertFalse(any(beat.scene_text == artwork.MARA_SHACKLE_FORGE_ART for beat in director.beats))

    def test_mara_illustration_shares_the_existing_refuge_shackle_explanation(self):
        for tobin in (False, True):
            with self.subTest(tobin=tobin):
                director, decisions = self.presented_decision(
                    "part2_house_under_ash", mara_present=True, tobin_present=tobin,
                )
                self.assertEqual(decisions, ["MARA TOUCHES THE COLD SHACKLE"])
                self.assertEqual(director.pages[-1].scene_text, artwork.MARA_SHACKLE_FORGE_ART)
                prose = " ".join(director.pages[-1].text.split())
                self.assertIn("Mara finds a cold shackle", prose)
                self.assertIn("she once wore", prose)
                self.assertTrue(director.beats[-1].has_narration)
                self.assertIn("recalls", director.pages[-1].scene_caption)


if __name__ == "__main__":
    unittest.main()
