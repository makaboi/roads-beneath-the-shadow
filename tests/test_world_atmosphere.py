"""Lighting stays architectural, decorative, deterministic and bounded."""

from dataclasses import replace
import importlib.util
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_world import WORLD_MAPS
from roads_beneath_shadow.world_atmosphere import (
    MAX_CACHED_MAPS, REGIONS, SIZE, TILE, WorldAtmosphere, light_sources,
    light_visible,
)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is required for native atmosphere tests")
class WorldAtmosphereTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pg = pygame
        pygame.init()
        pygame.display.set_mode((640, 480))

    @classmethod
    def tearDownClass(cls):
        cls.pg.quit()

    def setUp(self):
        self.atmosphere = WorldAtmosphere(self.pg)

    def picture(self, spec, time=0, reduced=False):
        surface = self.pg.Surface(SIZE)
        surface.fill((120, 132, 140))
        self.atmosphere.draw_ground(surface, spec, time, reduced_motion=reduced)
        self.atmosphere.finish(surface, spec, time, reduced_motion=reduced)
        return surface

    def test_light_cannot_cross_an_existing_wall_but_lights_its_near_face(self):
        grid = tuple("......#............." for _ in range(15))
        spec = replace(WORLD_MAPS["hall"], grid=grid, lights=((5, 5),))
        self.assertTrue(light_visible(grid, (5, 5), (6, 5)))
        self.assertFalse(light_visible(grid, (5, 5), (7, 5)))
        lighting = self.atmosphere.scene(spec).lighting[0]
        self.assertGreater(lighting.get_at((88, 85)).r, REGIONS["hall"].ambient[0])
        self.assertEqual(tuple(lighting.get_at((120, 85)))[:3], REGIONS["hall"].ambient)

    def test_carved_warden_stones_never_become_invented_lamps(self):
        for spec in WORLD_MAPS.values():
            stone_cells = {(x, y) for y, row in enumerate(spec.grid) for x, cell in enumerate(row) if cell == "L"}
            with self.subTest(world=spec.key):
                self.assertTrue(all((light.position[0] // TILE, light.position[1] // TILE) not in stone_cells for light in light_sources(spec)))
        self.assertEqual(light_sources(WORLD_MAPS["bridge"]), ())
        self.assertEqual(light_sources(WORLD_MAPS["refuge"]), ())

    def test_camp_remains_only_a_small_smokeless_ember(self):
        lights = light_sources(WORLD_MAPS["camp"])
        self.assertEqual(len(lights), 1)
        self.assertEqual(lights[0].kind, "ember")
        self.atmosphere.finish(self.pg.Surface(SIZE), WORLD_MAPS["camp"], 3.2)
        # The final emitter layer contains only the existing five-pixel coal.
        # Fog and water are separate material-clipped layers, never smoke.
        opaque = self.pg.mask.from_surface(self.atmosphere._layer, 0)
        self.assertEqual(opaque.count(), 5)
        self.assertEqual(opaque.get_bounding_rects()[0], self.pg.Rect(134, 121, 5, 1))

    def test_water_motion_never_spills_across_a_dry_shoreline(self):
        for key in ("camp", "watch-post", "wayhouse", "drowned-mile", "sluice"):
            spec = WORLD_MAPS[key]
            before = self.pg.Surface(SIZE)
            after = self.pg.Surface(SIZE)
            before.fill((110, 110, 110)); after.fill((110, 110, 110))
            self.atmosphere.draw_ground(before, spec, 0)
            self.atmosphere.draw_ground(after, spec, 18.75)
            changed_water = 0
            for y in range(SIZE[1]):
                for x in range(SIZE[0]):
                    if before.get_at((x, y)) != after.get_at((x, y)):
                        self.assertEqual(spec.grid[y // TILE][x // TILE], "~", (key, x, y))
                        changed_water += 1
            self.assertGreater(changed_water, 0, key)

    def test_echo_bridge_mist_stays_below_and_outside_the_wooden_deck(self):
        spec = WORLD_MAPS["bridge"]
        before = self.pg.Surface(SIZE); before.fill((110, 110, 110))
        after = before.copy()
        self.atmosphere.draw_ground(before, spec, 0)
        self.atmosphere.draw_ground(after, spec, 22)
        changed = 0
        for y in range(SIZE[1]):
            for x in range(SIZE[0]):
                if before.get_at((x, y)) != after.get_at((x, y)):
                    self.assertEqual(spec.grid[y // TILE][x // TILE], "X")
                    self.assertGreaterEqual(y, 155)
                    changed += 1
        self.assertGreater(changed, 0)

    def test_reduced_motion_freezes_every_region_at_arbitrary_times(self):
        for spec in WORLD_MAPS.values():
            with self.subTest(world=spec.key):
                first = self.pg.image.tobytes(self.picture(spec, 0, True), "RGB")
                later = self.pg.image.tobytes(self.picture(spec, 4813.7, True), "RGB")
                self.assertEqual(first, later)

    def test_region_lighting_applies_to_actors_without_moving_their_pixels(self):
        spec = WORLD_MAPS["lantern"]
        image = self.pg.Surface(SIZE)
        image.fill((0, 0, 0))
        self.pg.draw.rect(image, (240, 240, 240), (207, 84, 3, 3))
        self.pg.draw.rect(image, (240, 240, 240), (81, 180, 3, 3))
        self.atmosphere.finish(image, spec, 0, reduced_motion=True)
        self.assertGreater(image.get_at((208, 85)).r, image.get_at((82, 181)).r)
        self.assertEqual(image.get_at((80, 180)).r, 0)
        # Engine markers and native labels are drawn after this stage.
        self.pg.draw.rect(image, (248, 213, 126), (81, 180, 3, 3))
        self.assertEqual(tuple(image.get_at((82, 181)))[:3], (248, 213, 126))

    def test_rendering_is_deterministic_and_does_not_cache_elapsed_frames(self):
        spec = WORLD_MAPS["pony"]
        first = self.pg.image.tobytes(self.picture(spec, 7.5), "RGB")
        bank = self.atmosphere.scene(spec)
        surfaces = tuple(id(surface) for surface in bank.lighting)
        for time in (0, .1, 14, 540, 9700):
            self.picture(spec, time)
        self.assertEqual(self.atmosphere.cache_info, {"maps": 1, "lighting_frames": 4, "limit": MAX_CACHED_MAPS})
        self.assertEqual(tuple(id(surface) for surface in bank.lighting), surfaces)
        self.atmosphere = WorldAtmosphere(self.pg)
        self.assertEqual(first, self.pg.image.tobytes(self.picture(spec, 7.5), "RGB"))

    def test_geometry_variants_cannot_grow_the_native_surface_bank_unbounded(self):
        original = WORLD_MAPS["bree"]
        for index in range(MAX_CACHED_MAPS + 5):
            self.atmosphere.scene(replace(original, key=f"test-map-{index}"))
        self.assertEqual(self.atmosphere.cache_info["maps"], MAX_CACHED_MAPS)
        self.assertEqual(self.atmosphere.cache_info["lighting_frames"], MAX_CACHED_MAPS * 4)


if __name__ == "__main__":
    unittest.main()
