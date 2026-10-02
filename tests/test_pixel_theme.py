"""Installation and display-fit contracts for consistent desktop typography."""

from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from roads_beneath_shadow.pixel_theme import (
    AMBER, CARD, INK, MUTED, PANEL, PARCHMENT, RED, TEAL,
    FONT_DIRECTORY, draw_medallion, draw_pixel_frame,
    initial_window_size, load_font, missing_font_assets,
)


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

    def test_reading_inks_have_clear_contrast_on_both_charcoal_surfaces(self):
        def luminance(color):
            channels = [channel / 255 for channel in color]
            linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
            return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))
        for ink in (PARCHMENT, MUTED, AMBER, TEAL, RED):
            for surface in (INK, PANEL, CARD):
                with self.subTest(ink=ink, surface=surface):
                    ratio = (luminance(ink) + .05) / (luminance(surface) + .05)
                    self.assertGreaterEqual(ratio, 4.5)


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

    def test_ornament_never_paints_outside_the_frame_or_the_callers_clip(self):
        pg = self.pg
        sentinel = (243, 12, 231, 255)
        surface = pg.Surface((100, 90), pg.SRCALPHA)
        surface.fill(sentinel)
        rect = pg.Rect(11, 13, 68, 59)
        clip = pg.Rect(19, 20, 42, 39)
        surface.set_clip(clip)
        draw_pixel_frame(pg, surface, rect, ornate=True)
        self.assertEqual(surface.get_clip(), clip)
        for y in range(surface.get_height()):
            for x in range(surface.get_width()):
                if not clip.collidepoint(x, y):
                    self.assertEqual(surface.get_at((x, y)), sentinel)

    def test_medallion_keeps_crisp_pixels_inside_its_allocated_heading_space(self):
        pg = self.pg
        surface = pg.Surface((50, 50), pg.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        draw_medallion(pg, surface, (25, 25), radius=14)
        self.assertTrue(pg.Rect(11, 11, 29, 29).contains(surface.get_bounding_rect()))
        self.assertEqual(set(pg.image.tobytes(surface, "RGBA")[3::4]), {0, 255})
