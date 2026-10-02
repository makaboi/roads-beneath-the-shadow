"""Exploration must preserve live choices and keep every destination reachable."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_world import (
    ASSET_DIRECTORY,
    MAP_HEADINGS,
    TILE,
    WORLD_MAPS,
    WORLD_SIZE,
    WorldView,
    bind_points,
    interaction_tiles,
    map_for_request,
    shortest_path,
)


def request_for(key, options=None, identifier=1):
    spec = WORLD_MAPS[key]
    heading = next(heading for heading, map_key in MAP_HEADINGS.items() if map_key == key)
    options = options if options is not None else tuple(point.option for point in spec.points)
    return SimpleNamespace(identifier=identifier, kind="choice", label=heading, options=options, story=True)


class WorldRouteTests(unittest.TestCase):
    def test_every_live_destination_is_reachable_without_crossing_obstacles(self):
        for spec in WORLD_MAPS.values():
            self.assertEqual(len(spec.grid), 15)
            self.assertTrue(all(len(row) == 20 for row in spec.grid))
            self.assertTrue(spec.passable(spec.spawn))
            for point in spec.points:
                with self.subTest(world=spec.key, point=point.key):
                    routes = [shortest_path(spec, spec.spawn, target) for target in interaction_tiles(spec, point)]
                    self.assertTrue(any(routes) or spec.spawn in interaction_tiles(spec, point), "unreachable story choice")
                    for route in routes:
                        previous = spec.spawn
                        for tile in route:
                            self.assertTrue(spec.passable(tile))
                            self.assertEqual(abs(tile[0] - previous[0]) + abs(tile[1] - previous[1]), 1)
                            previous = tile

    def test_removed_or_reordered_options_keep_their_current_story_indices(self):
        spec = WORLD_MAPS["bree"]
        options = (spec.points[4].option, spec.points[1].option)
        bound = bind_points(spec, options)
        self.assertEqual([(point.point.key, point.answer) for point in bound], [("north_gate", 1), ("stable_yard", 2)])
        self.assertIs(map_for_request("WHERE WILL YOU INVESTIGATE?", options), spec)

    def test_unknown_heading_or_unmapped_new_option_keeps_the_normal_menu(self):
        options = (WORLD_MAPS["pony"].points[0].option,)
        self.assertIsNone(map_for_request("WHAT WILL YOU DO NEXT?", options))
        self.assertIsNone(map_for_request("WHAT WILL YOU DO?", (*options, "An unknown future route")))
        self.assertIsNone(map_for_request("WHAT WILL YOU DO?", ()))

    def test_optional_recovery_suffix_binds_to_the_reserved_lantern_location(self):
        option = "Rest and tend your wounds (recover up to 12 Health and all Focus)"
        spec = WORLD_MAPS["lantern"]
        self.assertIs(map_for_request("BEFORE THE LAST SEAL", (option,)), spec)
        bound, = bind_points(spec, (option,))
        self.assertEqual(bound.point.key, "rest")
        self.assertEqual(bound.option, option)

    def test_unreachable_and_outside_targets_do_not_create_a_path(self):
        spec = WORLD_MAPS["wayhouse"]
        self.assertEqual(shortest_path(spec, spec.spawn, (0, 0)), ())
        self.assertEqual(shortest_path(spec, spec.spawn, (-1, 5)), ())
        self.assertEqual(shortest_path(spec, spec.spawn, (1, 2)), ())  # flooded armory

    def test_optional_environmental_details_are_reachable_without_story_choices(self):
        for spec in WORLD_MAPS.values():
            for look in spec.looks:
                with self.subTest(world=spec.key, detail=look.key):
                    self.assertTrue(any(shortest_path(spec, spec.spawn, tile) for tile in interaction_tiles(spec, look)))
                    self.assertTrue(look.text)

    def test_original_world_art_is_packaged_at_native_resolution(self):
        for key in WORLD_MAPS:
            with self.subTest(world=key), Image.open(ASSET_DIRECTORY / f"world-{key}.png") as image:
                self.assertEqual(image.size, WORLD_SIZE)
                self.assertIsNotNone(image.getcolors(maxcolors=64))
        with Image.open(ASSET_DIRECTORY / "world-characters.png") as atlas:
            self.assertEqual(atlas.size, (80, 288))
            self.assertEqual(atlas.mode, "RGBA")
            self.assertIsNotNone(atlas.getcolors(maxcolors=64))
            # Walk cycle silhouettes and four facing directions are distinct.
            self.assertNotEqual(atlas.crop((0, 0, 20, 24)).tobytes(), atlas.crop((40, 0, 60, 24)).tobytes())
            self.assertNotEqual(atlas.crop((0, 0, 20, 24)).tobytes(), atlas.crop((0, 72, 20, 96)).tobytes())


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for world input tests")
class WorldSDLTests(unittest.TestCase):
    def setUp(self):
        import pygame
        self.pg = pygame
        pygame.init()
        pygame.display.set_mode((640, 480))
        self.world = WorldView(pygame)
        self.world.set_request(request_for("pony"))
        self.surface = pygame.Surface((640, 480))
        self.world.draw(self.surface, pygame.Rect(0, 0, 640, 480))

    def tearDown(self):
        self.pg.quit()

    def step(self, count=1, **kwargs):
        for _ in range(count):
            self.world.update(0.05, **kwargs)

    def test_click_walks_a_real_route_and_interaction_returns_the_live_choice(self):
        spec = WORLD_MAPS["pony"]
        target = spec.points[0]
        before = self.world.player_position
        click = self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=tuple(round(v * 2) for v in target.position))
        handled, answer = self.world.handle_event(click)
        self.assertTrue(handled)
        self.assertIsNone(answer)
        self.assertEqual(self.world.player_position, before, "click teleported the traveler")
        self.step()
        self.assertNotEqual(self.world.player_position, before)
        self.step(90)
        self.assertEqual(self.world.focused_option, 1)
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
        self.assertTrue(handled)
        self.assertEqual(answer, 1)

    def test_finished_conversations_keep_present_companions_and_hide_absent_ones(self):
        spec = WORLD_MAPS["lantern"]
        request = request_for("lantern")
        request.options = (spec.points[-1].option,)
        request.context = {"companions": [{"name": "Mara", "present": True}, {"name": "Tobin", "present": False}]}
        self.world.set_request(request)
        with patch.object(self.world, "_draw_character", wraps=self.world._draw_character) as draw:
            self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
        names = [call.args[0] for call in draw.call_args_list]
        self.assertIn("mara", names)
        self.assertIn("calenor", names)
        self.assertNotIn("tobin", names)
        self.assertFalse(self.world._navigation_spec.passable(spec.points[0].tile))
        self.assertTrue(self.world._navigation_spec.passable(spec.points[1].tile))

    def test_clicking_a_wall_and_interacting_at_distance_never_selects_a_choice(self):
        before = self.world.player_position
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(1, 1)))
        self.assertTrue(handled)
        self.assertIsNone(answer)
        self.step(50)
        self.assertEqual(self.world.player_position, before)
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
        self.assertTrue(handled)
        self.assertIsNone(answer)

    def test_the_visible_number_marker_is_also_a_click_target(self):
        point = WORLD_MAPS["pony"].points[0]
        x, y = point.position
        marker = (round((x + 7) * 2), round((y - 17) * 2))
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=marker))
        self.assertTrue(handled)
        self.assertIsNone(answer)
        self.assertEqual(self.world._clicked_point, point.key)
        self.step(90)
        self.assertEqual(self.world.focused_option, 1)

    def test_visible_npcs_block_walking_and_interactions_remain_available(self):
        self.world._position = (8 * TILE + 8, 8 * TILE + 8)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_w))
        self.step(50)
        self.assertGreaterEqual(self.world.player_position[1], 8 * TILE + 3)
        self.assertEqual(self.world.focused_option, 1)
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
        self.assertTrue(handled)
        self.assertEqual(answer, 1)

    def test_manual_movement_cannot_pass_through_a_table_even_after_a_stall(self):
        # Start immediately beneath a blocked table in the Pony.
        self.world._position = (6 * TILE + 8, 7 * TILE + 8)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_w))
        for _ in range(10):
            self.world.update(5.0)
        self.assertGreaterEqual(self.world.player_position[1], 7 * TILE + 3)
        self.assertTrue(self.world._position_clear(self.world.player_position))

    def test_menu_arrows_and_clicks_outside_the_world_remain_unhandled(self):
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_DOWN)), (False, None))
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(800, 300))), (False, None))

    def test_utilities_suspend_world_input_and_return_to_the_previous_position(self):
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_d))
        self.step(3)
        before = self.world.player_position
        self.world.set_request(SimpleNamespace(identifier=2, kind="choice", label="Inventory", options=("Back",), story=False))
        self.assertFalse(self.world.active)
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e)), (False, None))
        self.world.set_request(request_for("pony", identifier=3))
        self.assertEqual(self.world.player_position, before)
        self.step(2)
        self.assertEqual(self.world.player_position, before, "old held key leaked into resumed map")

    def test_missing_artwork_falls_back_to_a_playable_map(self):
        world = WorldView(self.pg)
        world.set_request(request_for("pony"))
        with patch.object(self.pg.image, "load", side_effect=self.pg.error("missing test asset")):
            world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
        target = WORLD_MAPS["pony"].points[0]
        self.assertTrue(world.walk_to(target.tile, point=target))
        for _ in range(90):
            world.update(0.05)
        handled, answer = world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
        self.assertTrue(handled)
        self.assertEqual(answer, 1)

    def test_looking_at_every_environmental_detail_never_submits_a_story_choice(self):
        for key, spec in WORLD_MAPS.items():
            for look in spec.looks:
                with self.subTest(world=key, detail=look.key):
                    self.world._positions.clear()
                    self.world.set_request(request_for(key, identifier=look.key))
                    self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
                    x, y = look.position
                    marker = (round(x * 2), round((y - 10) * 2))
                    handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=marker))
                    self.assertTrue(handled)
                    self.assertIsNone(answer)
                    self.assertEqual(self.world._clicked_point, "look:" + look.key)
                    self.step(220)
                    handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
                    self.assertTrue(handled)
                    self.assertIsNone(answer)
                    self.assertEqual(self.world._inspected_look, look)
                    self.assertIn(look.text, self.world.inspection_text)
                    self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
                    handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_ESCAPE))
                    self.assertTrue(handled)
                    self.assertIsNone(answer)
                    self.assertIsNone(self.world._inspected_look)

    def test_inspection_stops_a_held_walk_key_until_the_player_moves_again(self):
        self.world.set_request(request_for("bree", identifier=2))
        self.world._position = (11 * TILE + 8, 6 * TILE + 8)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_w))
        handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
        self.assertTrue(handled)
        self.assertIsNone(answer)
        look = self.world._inspected_look
        self.assertIsNotNone(look)
        before = self.world.player_position
        self.step(5)
        self.assertIs(self.world._inspected_look, look)
        self.assertEqual(self.world.player_position, before)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_a))
        self.step()
        self.assertIsNone(self.world._inspected_look)
        self.assertNotEqual(self.world.player_position, before)

    def test_reduced_motion_freezes_ambient_art_but_still_allows_walking(self):
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        first = self.pg.image.tobytes(self.surface, "RGB")
        self.step(30, reduced_motion=True)
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        self.assertEqual(first, self.pg.image.tobytes(self.surface, "RGB"))
        before = self.world.player_position
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_d))
        self.step(2, reduced_motion=True)
        self.assertNotEqual(self.world.player_position, before)

    def test_every_destination_can_be_walked_to_with_the_actual_collision_controller(self):
        for key, spec in WORLD_MAPS.items():
            for point in spec.points:
                with self.subTest(world=key, point=point.key):
                    self.world._positions.clear()
                    self.world.set_request(request_for(key, identifier=f"{key}-{point.key}"))
                    self.assertTrue(self.world.walk_to(point.tile, point=point))
                    self.step(220)
                    distance = ((self.world.player_position[0] - point.position[0]) ** 2 + (self.world.player_position[1] - point.position[1]) ** 2) ** 0.5
                    self.assertLessEqual(distance, self.world.INTERACTION_DISTANCE)
                    self.assertTrue(self.world._position_clear(self.world.player_position))


if __name__ == "__main__":
    unittest.main()
