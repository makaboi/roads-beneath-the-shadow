"""Exploration must preserve live choices and keep every destination reachable."""

import importlib.util
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from dataclasses import replace
from itertools import combinations
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
    MOTION_CHARACTERS,
    MOTION_ROWS,
    MOTION_FRAMES,
    DEPTH_OBJECTS,
    DEPTH_COLUMNS,
    DEPTH_CELL,
    WorldView,
    bind_points,
    interaction_tiles,
    map_for_request,
    shortest_path,
    hero_sprite_name,
    motion_frame_rect,
    origin_portrait_rect,
)
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


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
        with Image.open(ASSET_DIRECTORY / "world-depth.png") as atlas:
            rows = (len(DEPTH_OBJECTS) + DEPTH_COLUMNS - 1) // DEPTH_COLUMNS
            self.assertEqual(atlas.size, (DEPTH_COLUMNS * DEPTH_CELL[0], rows * DEPTH_CELL[1]))
            self.assertEqual(atlas.mode, "RGBA")
            self.assertIsNotNone(atlas.getcolors(maxcolors=64))

    def test_all_live_alternatives_bind_without_changing_their_text(self):
        for key, spec in WORLD_MAPS.items():
            heading = next(heading for heading, map_key in MAP_HEADINGS.items() if map_key == key)
            for point in spec.points:
                for option in (point.option, *point.aliases):
                    with self.subTest(world=key, option=option):
                        self.assertIs(map_for_request(heading, (option,)), spec)
                        bound, = bind_points(spec, (option,))
                        self.assertEqual((bound.point.key, bound.answer, bound.option), (point.key, 1, option))

    def test_origins_share_consistent_public_portraits_and_movement_identity(self):
        with Image.open(ASSET_DIRECTORY / "world-motion.png") as atlas, Image.open(ASSET_DIRECTORY / "world-portraits.png") as portraits:
            self.assertEqual(atlas.size, (20 * MOTION_FRAMES, len(MOTION_CHARACTERS) * MOTION_ROWS * 24))
            self.assertEqual(portraits.size, (60, 24))
            self.assertIsNotNone(atlas.getcolors(maxcolors=64))
            identities = []
            for origin in ORIGINS:
                with self.subTest(origin=origin.origin_id):
                    name = hero_sprite_name(origin.origin_id)
                    self.assertNotEqual(name, "traveler")
                    self.assertEqual(hero_sprite_name(origin.name), name)
                    x, y, w, h = motion_frame_rect(name)
                    portrait = origin_portrait_rect(origin.origin_id)
                    self.assertIsNotNone(portrait)
                    px, py, pw, ph = portrait
                    data = atlas.crop((x, y, x + w, y + h)).tobytes()
                    self.assertEqual(data, portraits.crop((px, py, px + pw, py + ph)).tobytes())
                    identities.append(data)
            self.assertEqual(len(set(identities)), len(ORIGINS))
            self.assertEqual(hero_sprite_name("future origin"), "traveler")
            self.assertIsNone(origin_portrait_rect(None))

    def test_idle_people_keep_their_boots_planted(self):
        with Image.open(ASSET_DIRECTORY / "world-motion.png") as atlas:
            for name in MOTION_CHARACTERS:
                if name == "warg":
                    continue
                for direction in range(4):
                    with self.subTest(character=name, direction=direction):
                        feet = []
                        for frame in range(MOTION_FRAMES):
                            x, y, w, h = motion_frame_rect(name, direction=direction, frame=frame)
                            feet.append(atlas.crop((x, y + 19, x + w, y + h)).tobytes())
                        self.assertEqual(len(set(feet)), 1)

    def test_actual_story_requests_activate_every_authored_world_for_all_origins(self):
        cases = (
            ("pony", "chapter1_decision", "_chapter_one_decision", {}, "WHAT WILL YOU DO?"),
            ("bree", "bree_exploration", "_bree_exploration", {}, "WHERE WILL YOU INVESTIGATE?"),
            ("north-gate", "north_gate", "_north_gate", {"north_gate_truth_chosen": True}, "HOW WILL YOU OPEN CALENOR'S CACHE?"),
            ("road-fork", "road_from_bree", "_road_from_bree", {}, "CHOOSE THE APPROACH TO MIDGEWATER"),
            ("camp", "midgewater_camp", "_midgewater_camp", {"midgewater_topic_chosen": True}, "WHO TAKES THE LAST WATCH?"),
            ("watch-post", "missing_watchman", "_missing_watchman", {}, "HOW DO YOU REACH NED?"),
            ("wayhouse", "wayhouse", "_wayhouse", {"wayhouse_opened": True}, "EXPLORE THE BURIED WAYHOUSE"),
            ("hall", "part2_hall_exploration", None, {}, "EXPLORE THE HALL OF EIGHT"),
            ("bridge", "part2_echo_bridge", None, {"part_two_hidden_route_known": True}, "HOW DO YOU REACH ECHO BRIDGE?"),
            ("bridge", "part2_echo_bridge", None, {}, "WHAT MUST SURVIVE AT ECHO BRIDGE?"),
            ("drowned-mile", "part2_drowned_mile", None, {}, "WHO DO YOU REACH FIRST?"),
            ("sluice", "part2_prisoners", None, {}, "THE SLUICE HORN SOUNDS. CHOOSE."),
            ("sluice", "part2_prisoners", None, {}, "HOW DO YOU FREE THEM?"),
            ("refuge", "part2_house_under_ash", None, {}, "CHOOSE A WAY THROUGH THE REFUGE"),
            ("lantern", "part2_vigil", None, {"part_two_mara_present": True, "part_two_tobin_present": True}, "BEFORE THE LAST SEAL"),
        )
        for origin in ORIGINS:
            for key, scene, method, flags, wanted in cases:
                with self.subTest(origin=origin.origin_id, scene=scene, heading=wanted), tempfile.TemporaryDirectory() as directory:
                    captured = []

                    class CapturingUI(TerminalUI):
                        def choose_story(self, heading, options):
                            if heading == wanted:
                                captured.append((heading, tuple(options)))
                                return None
                            return 1

                    ui = CapturingUI(fast=True, color=False, output_fn=lambda _text: None)
                    game = Game(ui, saves=SaveManager(Path(directory) / "saves"))
                    game.state = GameState(Character.from_origin("Mira", origin), scene=scene, chapter=2 if method is None else 1, flags=dict(flags))
                    game.state.character.hp -= 1
                    if method:
                        getattr(game, method)()
                    else:
                        game.part_two.run_scene(game.state)
                    self.assertEqual(len(captured), 1)
                    heading, options = captured[0]
                    self.assertIs(map_for_request(heading, options), WORLD_MAPS[key])
                    self.assertEqual(len(bind_points(WORLD_MAPS[key], options)), len(options))


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
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN)), (False, None))
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e)), (True, None))
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
                    self.assertEqual(self.world.inspection_title, look.name)
                    self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
                    handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_ESCAPE))
                    self.assertTrue(handled)
                    self.assertIsNone(answer)
                    self.assertIsNone(self.world._inspected_look)
                    self.assertEqual(self.world.inspection_title, "")

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

    def test_read_only_suspensions_restore_only_the_same_world_inspection(self):
        request = request_for("hall", identifier=2)
        request.context = {"journey_id": "same-journey", "presentation_id": 1}
        look = WORLD_MAPS["hall"].looks[1]

        def inspect():
            self.world.set_request(request)
            self.assertTrue(self.world.walk_to(look.tile, point=look))
            self.step(120)
            self.world._clicked_point = "look:" + look.key
            self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
            self.assertEqual(self.world.inspection_title, look.name)

        inspect()
        position = self.world.player_position
        self.world.set_request(None, preserve_inspection=True)
        self.assertEqual(self.world.inspection_title, "")
        self.world.set_request(None, preserve_inspection=True)
        self.world.set_request(request)
        self.assertEqual(self.world.inspection_title, look.name)
        self.assertEqual(self.world.player_position, position)

        self.world.set_request(None, preserve_inspection=True)
        request.identifier = 3  # An engine utility issues a fresh request.
        self.world.set_request(request)
        self.assertEqual(self.world.inspection_title, look.name)

        self.world.set_request(None, preserve_inspection=True)
        request.context["presentation_id"] = 2  # Earlier save, same journey.
        self.world.set_request(request)
        self.assertFalse(self.world.inspection_open)

        inspect()
        self.world.set_request(None, preserve_inspection=True)
        request.options = request.options[1:]
        request.identifier = 4
        self.world.set_request(request)
        self.assertFalse(self.world.inspection_open)

        inspect()
        self.world.set_request(None, preserve_inspection=True)
        self.world.set_request(None)  # A real story answer clears the latch.
        self.world.set_request(request)
        self.assertFalse(self.world.inspection_open)

        inspect()
        self.world.set_request(None, preserve_inspection=True)
        self.world.set_request(request_for("bree", identifier=5))
        self.assertFalse(self.world.inspection_open)

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

    def test_focus_loss_and_public_stop_cancel_planned_and_held_movement(self):
        target = WORLD_MAPS["pony"].points[0]
        self.world.walk_to(target.tile, point=target)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_d))
        self.world.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        before = self.world.player_position
        self.step(5)
        self.assertEqual(self.world.player_position, before)
        self.assertFalse(self.world._path)
        self.assertFalse(self.world._held)
        self.world.walk_to(target.tile, point=target)
        self.world.stop_moving()
        self.step(5)
        self.assertEqual(self.world.player_position, before)

    def test_interaction_cannot_cut_diagonally_through_a_wall(self):
        spec = WORLD_MAPS["pony"]
        grid = [list("." * 20) for _ in range(15)]
        grid[2][3] = "#"
        point = replace(spec.points[0], tile=(3, 3), sprite=None)
        self.world.spec = replace(spec, grid=tuple("".join(row) for row in grid), points=(point,), looks=())
        self.world._navigation_spec = self.world.spec
        self.world.points = bind_points(self.world.spec, (point.option,))
        self.world._position = (2 * TILE + 8, 2 * TILE + 8)
        self.assertIsNone(self.world.focused_option)
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e)), (True, None))
        self.assertTrue(self.world.walk_to(point.tile, point=point))
        self.step(80)
        self.assertEqual(self.world.focused_option, 1)

    def test_new_journey_resets_world_positions_while_utilities_preserve_them(self):
        request = request_for("road-fork", identifier=2)
        request.context = {"journey_id": "first", "origin": "healers_apprentice"}
        self.world.set_request(request)
        self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_w))
        self.step(8)
        previous = self.world.player_position
        request.identifier = 3
        self.world.set_request(request)
        self.assertEqual(self.world.player_position, previous)
        request.identifier = 4
        request.context["journey_id"] = "second"
        self.world.set_request(request)
        spec = WORLD_MAPS["road-fork"]
        self.assertEqual(self.world.player_position, (spec.spawn[0] * TILE + 8, spec.spawn[1] * TILE + 8))
        self.assertEqual(self.world._hero_name, "healer")
        self.assertEqual(self.world._direction, 0)

    def test_facing_belongs_to_each_map_when_returning_from_another_scene(self):
        self.world._direction = 1
        self.world.set_request(request_for("bree", identifier=2))
        self.assertEqual(self.world._direction, 0)
        self.world._direction = 3
        self.world.set_request(request_for("pony", identifier=3))
        self.assertEqual(self.world._direction, 1)
        self.world.set_request(request_for("bree", identifier=4))
        self.assertEqual(self.world._direction, 3)

    def test_loading_an_earlier_save_resets_positions_but_continue_preserves_them(self):
        import threading
        from roads_beneath_shadow.pixel_ui import PixelUI

        state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="road_from_bree")
        current = [state]
        ui = PixelUI(fast=True, sound=False)
        ui.state_provider = lambda: current[0]
        spec = WORLD_MAPS["road-fork"]
        template = request_for(spec.key)

        def live_request(kind="choice"):
            worker = threading.Thread(target=lambda: ui._request(
                kind, template.label if kind == "choice" else "Continue",
                template.options if kind == "choice" else (), story=kind == "choice",
            ))
            worker.start()
            event = ui.events.get(timeout=2)
            self.assertEqual(event.kind, "request")
            request = event.data["request"]
            ui.submit(request, None)
            worker.join(2)
            self.assertFalse(worker.is_alive())
            return request

        try:
            with tempfile.TemporaryDirectory() as directory:
                saves = SaveManager(Path(directory))
                saves.save(1, state)
                original = live_request()
                self.world.set_request(original)
                self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_w))
                self.step(8)
                self.world.stop_moving()
                position = self.world.player_position
                party = self.world.party_positions
                self.world.set_request(live_request("pause"))
                continued = live_request()
                self.assertEqual(original.context["presentation_id"], continued.context["presentation_id"])
                self.world.set_request(continued)
                self.assertEqual(self.world.player_position, position)
                self.assertEqual(self.world.party_positions, party)

                current[0] = saves.load(1)
                loaded = live_request()
                self.assertEqual(loaded.context["journey_id"], original.context["journey_id"])
                self.assertNotEqual(loaded.context["presentation_id"], original.context["presentation_id"])
                self.world.set_request(loaded)
                self.assertEqual(self.world.player_position, (spec.spawn[0] * TILE + 8, spec.spawn[1] * TILE + 8))
                self.assertEqual(self.world._direction, 0)
                self.assertEqual(tuple(self.world._trail), (self.world.player_position,))
        finally:
            ui.close()

    def test_returning_companion_never_traps_a_restored_traveler(self):
        request = request_for("lantern", identifier=2)
        request.context = {"companions": [{"name": "Mara", "present": False}]}
        self.world.set_request(request)
        self.world._position = WORLD_MAPS["lantern"].points[0].position
        request.identifier = 3
        request.context["companions"][0]["present"] = True
        self.world.set_request(request)
        self.assertTrue(self.world._position_clear(self.world.player_position))
        self.assertNotEqual(self.world.player_position, WORLD_MAPS["lantern"].points[0].position)

    def test_followers_walk_around_water_and_do_not_block_a_story_approach(self):
        request = request_for("watch-post", identifier=2)
        request.context = {"companions": [{"name": "Mara", "present": True}, {"name": "Tobin", "present": True}]}
        self.world.set_request(request)
        before = self.world.party_positions
        self.assertEqual(set(before), {"mara", "tobin"})
        point = WORLD_MAPS["watch-post"].points[0]
        self.world.walk_to(point.tile, point=point)
        for _ in range(180):
            self.step()
            for position in self.world.party_positions.values():
                self.assertTrue(self.world._position_clear(position), "follower crossed water or a wall")
        self.assertNotEqual(self.world.party_positions, before)
        self.assertEqual(self.world.focused_option, 1)
        for position in self.world.party_positions.values():
            self.assertNotIn(self.world._tile(position), self.world._reserved_tiles())
            self.assertTrue(self.world._navigation_spec.passable(self.world._tile(position)))
        request.identifier = 3
        request.context["companions"][1]["present"] = False
        self.world.set_request(request)
        self.assertEqual(set(self.world.party_positions), {"mara"})

    def test_companions_keep_up_during_continuous_walking_and_turning(self):
        from math import hypot

        self.world.set_request(request_for("hall", identifier=2))
        circuit = ((4, 6), (15, 6), (15, 12), (4, 12))
        for target in circuit * 8:
            self.assertTrue(self.world.walk_to(target))
            for _ in range(1200):
                self.world.update(1 / 60)
                for position in self.world.party_positions.values():
                    self.assertTrue(self.world._position_clear(position))
                    self.assertLess(hypot(position[0] - self.world.player_position[0], position[1] - self.world.player_position[1]), 90)
                if not self.world._path:
                    break
            else:
                self.fail("A continuous circuit left the traveler walking forever")

    def test_missing_motion_art_keeps_every_new_character_and_choice_playable(self):
        world = WorldView(self.pg)
        with patch.object(self.pg.image, "load", side_effect=self.pg.error("missing test asset")):
            for key in ("watch-post", "bridge", "sluice"):
                world.set_request(request_for(key, identifier=key))
                world.draw(self.surface, self.pg.Rect(0, 0, 640, 480))
                for bound in world.points:
                    self.assertTrue(world.walk_to(bound.point.tile, point=bound.point))

    def test_boardwalk_and_marsh_have_distinct_footstep_materials(self):
        for key, tile, material in (("pony", (9, 10), "wood"), ("bridge", (10, 7), "wood"), ("camp", (9, 11), "mud"), ("road-fork", (8, 9), "grass"), ("hall", (10, 12), "stone")):
            with self.subTest(world=key):
                self.world.set_request(request_for(key, identifier=key))
                self.world._position = (tile[0] * TILE + 8, tile[1] * TILE + 8)
                self.assertEqual(self.world.surface_kind, material)

    def test_completed_room_variants_keep_every_remaining_option_reachable_and_correct(self):
        for key in ("bree", "wayhouse", "hall", "lantern"):
            spec = WORLD_MAPS[key]
            optional = spec.points[:-1]
            for count in range(len(optional) + 1):
                for subset in combinations(optional, count):
                    options = tuple(point.option for point in (*subset, spec.points[-1]))
                    request = request_for(key, options, identifier=(key, options))
                    request.context = {"companions": [{"name": "Mara", "present": True}, {"name": "Tobin", "present": True}]}
                    for expected, point in enumerate((*subset, spec.points[-1]), 1):
                        with self.subTest(world=key, options=options, destination=point.key):
                            self.world._positions.clear()
                            self.world.set_request(request)
                            self.assertTrue(self.world.walk_to(point.tile, point=point))
                            self.world._clicked_point = point.key
                            self.step(220)
                            handled, answer = self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e))
                            self.assertTrue(handled)
                            self.assertEqual(answer, expected)

    def test_unknown_hidden_stair_has_no_marker_or_revealed_art(self):
        spec = WORLD_MAPS["bridge"]
        self.world.set_request(request_for("bridge", (spec.points[0].option,), identifier=2))
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        hidden = self.world._native.subsurface((49, 48, 14, 15)).copy()
        self.assertEqual([bound.point.key for bound in self.world.points], ["bridgehead"])
        self.world.set_request(request_for("bridge", (spec.points[0].option, spec.points[1].option), identifier=3))
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        known = self.world._native.subsurface((49, 48, 14, 15))
        self.assertNotEqual(self.pg.image.tobytes(hidden, "RGB"), self.pg.image.tobytes(known, "RGB"))
        known = known.copy()
        request = request_for("bridge", (spec.points[2].option, spec.points[3].option), identifier=4)
        request.label = "WHAT MUST SURVIVE AT ECHO BRIDGE?"
        self.world.set_request(request)
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        self.assertEqual(self.pg.image.tobytes(known, "RGB"), self.pg.image.tobytes(self.world._native.subsurface((49, 48, 14, 15)), "RGB"))
        request = request_for("bridge", (spec.points[0].option,), identifier=5)
        self.world.set_request(request)
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        self.assertEqual(self.pg.image.tobytes(hidden, "RGB"), self.pg.image.tobytes(self.world._native.subsurface((49, 48, 14, 15)), "RGB"))

    def test_reduced_motion_is_still_on_every_map_and_companion_formation(self):
        for key in WORLD_MAPS:
            with self.subTest(world=key):
                self.world.set_request(request_for(key, identifier=key))
                self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
                before = self.pg.image.tobytes(self.surface, "RGB")
                self.step(20, reduced_motion=True)
                self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
                self.assertEqual(before, self.pg.image.tobytes(self.surface, "RGB"))

    def test_interacting_on_the_way_to_a_new_target_does_not_submit_the_previous_choice(self):
        spec = WORLD_MAPS["pony"]
        self.world._position = (8 * TILE + 8, 8 * TILE + 8)
        self.assertEqual(self.world.focused_option, 1)
        target = spec.points[1]
        self.world._clicked_point = target.key
        self.assertTrue(self.world.walk_to(target.tile, point=target))
        self.assertIn(target.name, self.world.hint_text)
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e)), (True, None))
        self.step(120)
        self.assertEqual(self.world.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_e)), (True, 2))

    def test_a_blocked_click_cancels_the_old_path_and_explains_the_collision(self):
        target = WORLD_MAPS["pony"].points[0]
        self.assertTrue(self.world.walk_to(target.tile, point=target))
        self.assertFalse(self.world.walk_to((0, 0)))
        before = self.world.player_position
        self.step(5)
        self.assertEqual(self.world.player_position, before)
        self.assertIn("cannot be crossed", self.world.hint_text)
        self.step(40)
        self.assertNotIn("cannot be crossed", self.world.hint_text)

    def test_tall_foliage_occludes_a_traveler_on_its_northern_side(self):
        self.world.set_request(request_for("bree", identifier=2))
        self.world._position = (6 * TILE + 8, 1 * TILE + 8)
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        behind = self.world._native.subsurface((96, 20, 16, 9)).copy()
        sprites = self.world._depth_sprites
        self.world._depth_sprites = {}
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        flat = self.world._native.subsurface((96, 20, 16, 9))
        self.assertNotEqual(self.pg.image.tobytes(behind, "RGB"), self.pg.image.tobytes(flat, "RGB"))
        self.world._position = (6 * TILE + 8, 3 * TILE + 8)
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        flat_feet = self.world._native.subsurface((96, 50, 16, 9)).copy()
        self.world._depth_sprites = sprites
        self.world.draw(self.surface, self.pg.Rect(0, 0, 640, 480), reduced_motion=True)
        front_feet = self.world._native.subsurface((96, 50, 16, 9))
        self.assertEqual(self.pg.image.tobytes(flat_feet, "RGB"), self.pg.image.tobytes(front_feet, "RGB"))


if __name__ == "__main__":
    unittest.main()
