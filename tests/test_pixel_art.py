"""Every scene the story can display must ship in the graphical package."""

import unittest

from PIL import Image

from roads_beneath_shadow import artwork, journey_artwork, part_two_artwork, pixel_art


class PixelArtworkTests(unittest.TestCase):
    def test_every_story_illustration_and_animation_has_a_bundled_scene(self):
        self.assertEqual(pixel_art.missing_assets(), [])
        for module in (artwork, journey_artwork, part_two_artwork):
            for name, value in vars(module).items():
                if not name.isupper():
                    continue
                frames = getattr(value, "frames", ())
                if isinstance(value, str):
                    frames = (value, *frames)
                elif isinstance(value, tuple):
                    frames = value
                for frame in frames:
                    if isinstance(frame, str):
                        with self.subTest(scene=name):
                            self.assertTrue(pixel_art.resolve_scene(frame).is_file())

    def test_pixel_assets_are_native_resolution_with_a_restrained_palette(self):
        for path in pixel_art.ASSET_DIR.glob("*.png"):
            if path.name.startswith("world-"):
                continue
            with self.subTest(scene=path.name), Image.open(path) as scene:
                self.assertEqual(scene.size, (320, 240))
                colors = scene.convert("RGB").getcolors(maxcolors=32)
                self.assertIsNotNone(colors, "scene exceeds the pixel-art palette")

    def test_key_story_subjects_keep_their_distinct_illustrations(self):
        expected = (
            (artwork.TITLE_ART_EXPANDED, "title"),
            (artwork.PRANCING_PONY_INTERIOR_ART, "tavern-interior"),
            (artwork.MARSH_WARG_INTRO_ART, "warg"),
            (artwork.GHORAK_ASH_HAND_INTRO_ART, "ghorak"),
            (artwork.BLACK_RIDER_CLIFFHANGER_ART, "rider"),
            (artwork.STAR_KEY_BROKEN_ART, "broken-key"),
            (part_two_artwork.FINAL_SEAL_BATTLE_ART, "seal"),
        )
        for illustration, subject in expected:
            self.assertEqual(pixel_art.resolve_scene(illustration).stem, subject)
