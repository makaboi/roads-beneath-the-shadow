"""Installation and display-fit contracts for consistent desktop typography."""

from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from roads_beneath_shadow.pixel_theme import FONT_DIRECTORY, initial_window_size, load_font, missing_font_assets


class DisplayFitTests(unittest.TestCase):
    def test_common_laptop_displays_leave_room_for_window_chrome(self):
        for desktop in ((1280, 720), (1366, 768), (1440, 900), (1920, 1080)):
            with self.subTest(desktop=desktop):
                size = initial_window_size(desktop)
                self.assertLessEqual(size[0], desktop[0] - 48)
                self.assertLessEqual(size[1], desktop[1] - 80)
                self.assertGreaterEqual(size[0], 760)
                self.assertGreaterEqual(size[1], 560)

    def test_unavailable_desktop_dimensions_use_a_known_layout(self):
        self.assertEqual(initial_window_size((0, 0)), (1200, 900))

    def test_bundled_typefaces_and_license_exist(self):
        self.assertEqual(missing_font_assets(), [])
        license_text = (FONT_DIRECTORY / "LICENSE.txt").read_text()
        self.assertIn("Permission is hereby granted", license_text)
        self.assertIn("Bitstream", license_text)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for font checks")
class BundledFontTests(unittest.TestCase):
    def setUp(self):
        import pygame
        self.pg = pygame
        pygame.font.init()

    def tearDown(self):
        self.pg.quit()

    def test_font_loading_is_independent_of_system_family_resolution(self):
        with patch.object(self.pg.font, "SysFont", side_effect=AssertionError("native font must not be used")):
            regular = load_font(self.pg, 17)
            bold = load_font(self.pg, 24, bold=True)
        self.assertGreater(regular.size("Éowen — the road remembers")[0], 0)
        self.assertGreater(bold.render("ROADS", False, (255, 255, 255)).get_width(), 0)

    def test_damaged_font_installation_falls_back_to_a_readable_font(self):
        with patch("roads_beneath_shadow.pixel_theme.FONT_DIRECTORY", FONT_DIRECTORY / "missing"):
            font = load_font(self.pg, 17)
        self.assertGreater(font.size("Return to the road")[0], 0)
