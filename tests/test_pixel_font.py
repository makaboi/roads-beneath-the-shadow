"""Offline glyph coverage and source-preserving measured presentation."""

from __future__ import annotations

import copy
import gc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_font import (
    COVERAGE_FILE, FALLBACK_LICENSE, FONT_CACHE_LIMIT, FONT_NAMES, LAYOUT_CACHE_LIMIT,
    MAX_COVERAGE_BYTES, FallbackFont, _load_coverage, caret_positions,
    text_clusters, text_viewport, validate_fallback_assets,
)
from roads_beneath_shadow.pixel_theme import FONT_DIRECTORY, load_font, wrap_text
from roads_beneath_shadow.text_input import TextEntry


class FontAssetTests(unittest.TestCase):
    def test_imports_do_not_import_pygame_or_open_sdl(self):
        script = ("import sys; import roads_beneath_shadow.pixel_font; "
                  "import roads_beneath_shadow.pixel_theme; assert 'pygame' not in sys.modules")
        completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_strict_assets_include_actual_full_coverage_and_licenses(self):
        result = validate_fallback_assets(FONT_DIRECTORY)
        self.assertEqual(result["fonts"]["RBSRoadCJK-Regular.otf"]["codepoints"], 44810)
        self.assertEqual(result["fonts"]["NotoSansDevanagari-Regular.ttf"]["codepoints"], 272)
        coverage = _load_coverage(str(FONT_DIRECTORY))
        self.assertTrue(all(coverage["cjk"].contains(c) for c in "夜道の旅人김민준"))
        self.assertTrue(all(coverage["devanagari"].contains(c) for c in "नंदिनीश्रद्धा"))
        self.assertFalse(any(coverage["regular"].contains(c) for c in "夜道の旅人नंदिनी"))
        with self.assertRaises(TypeError):
            coverage["cjk"] = coverage["regular"]
        license_text = (FONT_DIRECTORY / FALLBACK_LICENSE).read_text(encoding="utf-8")
        self.assertIn("2014-2021 Adobe", license_text)
        self.assertIn("2015 Google", license_text)
        self.assertIn("renamed", license_text)

    def test_strict_asset_validation_rejects_bad_types_ranges_paths_and_bytes(self):
        original = json.loads((FONT_DIRECTORY / COVERAGE_FILE).read_text())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for filename in (*FONT_NAMES.values(), FALLBACK_LICENSE):
                shutil.copyfile(FONT_DIRECTORY / filename, directory / filename)
            cases = []
            data = copy.deepcopy(original); data["schema"] = True; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["filename"] = "/tmp/foreign.otf"; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["ranges"][0] = [True, 40]; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["ranges"][0] = [40, 39]; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["ranges"][1] = data["fonts"]["cjk"]["ranges"][0]; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["codepoints"] = 44810.0; cases.append(data)
            data = copy.deepcopy(original); data["fonts"]["cjk"]["sha256"] = "0" * 64; cases.append(data)
            for data in cases:
                (directory / COVERAGE_FILE).write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    validate_fallback_assets(directory)
            (directory / COVERAGE_FILE).write_text(" " * (MAX_COVERAGE_BYTES + 1))
            with self.assertRaises(ValueError):
                validate_fallback_assets(directory)
            (directory / COVERAGE_FILE).write_text(json.dumps(original))
            (directory / FONT_NAMES["cjk"]).unlink()
            with self.assertRaisesRegex(ValueError, "RBSRoadCJK"):
                validate_fallback_assets(directory)
            shutil.copyfile(FONT_DIRECTORY / FONT_NAMES["cjk"], directory / FONT_NAMES["cjk"])
            with (directory / FONT_NAMES["cjk"]).open("r+b") as font:
                font.write(b"bad!")
            with self.assertRaisesRegex(ValueError, "checksum"):
                validate_fallback_assets(directory)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for glyph rendering")
class MeasuredFontTests(unittest.TestCase):
    def setUp(self):
        import pygame
        self.pg = pygame
        pygame.font.init()

    def tearDown(self):
        self.pg.quit()

    def rgba(self, surface):
        return self.pg.image.tobytes(surface, "RGBA")

    def ink_count(self, surface):
        alpha = self.pg.Surface(surface.get_size(), self.pg.SRCALPHA)
        alpha.blit(surface, (0, 0))
        return sum(value != 0 for value in self.rgba(alpha)[3::4])

    def test_base_text_pixels_metrics_and_styles_remain_exact_without_fallback_io(self):
        values = ("ROADS BENEATH THE SHADOW", "Éowen — the road remembers", "Дмитрий", "Αριάδνη", "E\u0301owen")
        for size in (13, 17, 20, 23, 27):
            for bold in (False, True):
                font = load_font(self.pg, size, bold=bold)
                for setter in ("set_bold", "set_italic", "set_underline", "set_strikethrough"):
                    getattr(font, setter)(True)
                    with patch.object(self.pg.font, "Font", side_effect=AssertionError("covered text opened a fallback")):
                        for text in values:
                            self.assertEqual(font.size(text), font.base.size(text))
                            self.assertEqual(font.metrics(text), font.base.metrics(text))
                            self.assertEqual(caret_positions(font, text), tuple(font.base.size(text[:i])[0] for i in range(len(text) + 1)))
                            for antialias in (False, True):
                                self.assertEqual(self.rgba(font.render(text, antialias, (239, 225, 188))),
                                                 self.rgba(font.base.render(text, antialias, (239, 225, 188))))
                    getattr(font, setter)(False)
                self.assertEqual(len(font._fonts), 0)

    def test_missing_base_glyphs_use_distinct_bundled_cjk_and_devanagari_outlines(self):
        font = load_font(self.pg, 23)
        self.assertNotEqual(self.rgba(font.render("夜", False, "white")), self.rgba(font.render("道", False, "white")))
        self.assertNotEqual(self.rgba(font.render("न", False, "white")), self.rgba(font.render("द", False, "white")))
        self.assertTrue(all(metric is not None for metric in font.metrics("夜道नद")))
        for text in ("夜道の旅人", "नंदिनी", "श्रद्धा", "क्षत्रिय"):
            self.assertNotEqual(self.rgba(font.render(text, False, "white")), self.rgba(font.base.render(text, False, "white")))
        self.assertTrue(font.shaping_available)

    def test_fallback_ink_fits_original_line_band_with_faithful_dimensions(self):
        values = ("夜道の旅人", "李明·山田太郎", "नंदिनी", "श्रीकृष्ण", "अर्जुन", "श्रद्धा", "क्षत्रिय", "한글")
        for size in (13, 17, 20, 23, 27):
            for bold in (False, True):
                font = load_font(self.pg, size, bold=bold)
                for text in values:
                    layout = font._layout(text)
                    self.assertEqual(layout.height, font.base.get_height())
                    self.assertEqual(font.get_linesize(), font.base.get_linesize())
                    for antialias in (False, True):
                        image = font.render(text, antialias, "white")
                        self.assertEqual(image.get_size(), font.size(text))
                        expected_ink = 0
                        for run in layout.runs:
                            raw = font._raw_render(font._font(run.kind, run.point_size), run.text, antialias, "white")
                            expected_ink += self.ink_count(raw)
                        self.assertEqual(self.ink_count(image), expected_ink, (size, bold, text, antialias))
                        self.assertGreater(expected_ink, 0)

    def test_cjk_variation_selectors_and_zero_width_names_do_not_become_separate_boxes(self):
        for size in (17, 20, 23, 27):
            font = load_font(self.pg, size)
            for text in ("\u3402\U000e0100", "\u3001\ufe00", "か\u3099", "夜\ufe0f"):
                runs = font._layout(text).runs
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0].text, text)
                self.assertEqual(font.render(text, False, "white").get_size(), font.size(text))
            for text in ("", "\ufe00", "\U000e0100", "\ufe00夜"):
                self.assertEqual(font.render(text, False, "white").get_size(), font.size(text))
                advances = caret_positions(font, text)
                self.assertEqual(len(advances), len(text) + 1)
                self.assertEqual(list(advances), sorted(advances))

    def test_decomposed_hangul_shapes_identically_without_normalizing_the_source(self):
        decomposed, composed = "한글", "한글"
        for size in (13, 17, 20, 23, 27):
            font = load_font(self.pg, size)
            self.assertEqual(font.size(decomposed), font.size(composed))
            self.assertEqual(self.rgba(font.render(decomposed, False, "white")),
                             self.rgba(font.render(composed, False, "white")))
            self.assertEqual("".join(text_clusters(decomposed)), decomposed)
            self.assertEqual(len(list(text_clusters(decomposed))), 2)

    def test_wrapping_keeps_combining_conjunct_hangul_and_variation_clusters(self):
        values = ("夜道の旅人" * 4, "か\u3099き\u3099", "नंदिनीनंदिनीनंदिनी", "श्रद्धाक्षत्रिय", "한글", "\u3402\U000e0100夜道")
        for size in (17, 20, 23):
            font = load_font(self.pg, size)
            for text in values:
                clusters = list(text_clusters(text))
                for width in (30, 80, 170):
                    rows = wrap_text(text, font, width)
                    self.assertEqual("".join(rows), text)
                    consumed = 0
                    boundaries = {0}
                    for cluster in clusters:
                        consumed += len(cluster); boundaries.add(consumed)
                    consumed = 0
                    maximum = max(width, *(font.size(cluster)[0] for cluster in clusters))
                    for row in rows:
                        consumed += len(row)
                        self.assertIn(consumed, boundaries)
                        self.assertLessEqual(font.size(row)[0], maximum)

    def test_shaped_caret_offsets_are_bounded_monotone_and_preserve_editor_values(self):
        for size in (17, 20, 22, 23, 27):
            font = load_font(self.pg, size)
            for text in ("Éowen — 夜道の旅人", "श्रद्धा", "क्षत्रिय", "नंदिनी", "한글", "\u3402\U000e0100", "\ufe00", ""):
                editor = TextEntry(text, max_length=24)
                positions = caret_positions(font, editor.text)
                self.assertEqual(len(positions), len(editor.text) + 1)
                self.assertEqual(positions[0], 0)
                self.assertEqual(positions[-1], font.size(editor.text)[0])
                self.assertEqual(list(positions), sorted(positions))
                self.assertTrue(all(0 <= x <= font.size(editor.text)[0] for x in positions))
                source = editor.text
                editor.home()
                previous = 0
                while editor.cursor < len(editor.text):
                    editor.navigate(1)
                    self.assertGreaterEqual(positions[editor.cursor], previous)
                    previous = positions[editor.cursor]
                self.assertEqual(editor.text, source)
                editor.select_all(); editor.insert("夜道"); self.assertEqual(editor.text, "夜道")

    def test_viewport_keeps_whole_clusters_at_every_source_caret_and_preferred_start(self):
        values = (("夜道の旅人 — श्रद्धा — क्षत्रिय " * 3)[:64],
                  ("夜\u3402\U000e0100道" * 16), "한글 — नंदिनी", "\ufe00夜", "")
        for size in (17, 20, 23, 27):
            font = load_font(self.pg, size)
            for text in values:
                boundaries = {0}; consumed = 0
                for cluster in text_clusters(text):
                    consumed += len(cluster); boundaries.add(consumed)
                for caret in range(len(text) + 1):
                    for preferred in (0, max(0, caret - 3), caret, len(text)):
                        for width in (1, 30, 92, 250):
                            start, end = text_viewport(font, text, width, caret,
                                                       preferred_start=preferred, prefix_width=20, caret_padding=10)
                            self.assertIn(start, boundaries)
                            self.assertIn(end, boundaries)
                            self.assertTrue(0 <= start <= caret <= end <= len(text))
                            if text:
                                self.assertGreater(end, start)

    def test_viewport_accounts_for_ellipsis_padding_and_overwide_first_cluster(self):
        font = load_font(self.pg, 23)
        self.assertEqual(text_viewport(font, "", 1, 40), (0, 0))
        self.assertEqual(text_viewport(font, "श्रद्धा", 1, 1), (0, 3))
        self.assertEqual(text_viewport(font, "\u3402\U000e0100", 1, 1), (0, 2))
        text = "夜" * 24
        start, end = text_viewport(font, text, 92, 24, prefix_width=20, caret_padding=10)
        self.assertGreater(start, 0)
        self.assertEqual(end, len(text))
        self.assertLessEqual(font.size(text[start:])[0] + 20 + 10, 92)
        start, end = text_viewport(font, "श्रद्धा", 100, 5, preferred_start=2)
        self.assertEqual((start, end), (0, 7))

    def test_layouts_fonts_and_warm_frame_io_are_bounded(self):
        font = load_font(self.pg, 17)
        for number in range(LAYOUT_CACHE_LIMIT + 40):
            font.render(f"旅人{number}", False, "white")
        self.assertEqual(len(font._layouts), LAYOUT_CACHE_LIMIT)
        self.assertLessEqual(len(font._fonts), FONT_CACHE_LIMIT)
        long_text = "夜" * 513
        font.size(long_text)
        self.assertNotIn(long_text, font._layouts)
        font.render("Mira — 夜道 श्रद्धा", False, "white")
        with patch.object(self.pg.font, "Font", side_effect=AssertionError("warm frame reopened a font")):
            for _ in range(5):
                self.assertEqual(font.size("Mira — 夜道 श्रद्धा"), font.render("Mira — 夜道 श्रद्धा", False, "white").get_size())

    def test_missing_fallback_or_index_degrades_once_and_strict_diagnostic_rejects_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for filename in ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", COVERAGE_FILE, FALLBACK_LICENSE):
                shutil.copyfile(FONT_DIRECTORY / filename, directory / filename)
            font = replacement = None
            try:
                font = FallbackFont(self.pg, self.pg.font.Font(str(directory / "DejaVuSansMono.ttf"), 17),
                                    17, bold=False, font_directory=directory)
                original = self.pg.font.Font
                with patch.object(self.pg.font, "Font", wraps=original) as opening:
                    for text in ("夜", "道", "한", "न", "द"):
                        self.assertEqual(font.size(text), font.render(text, False, "white").get_size())
                    self.assertEqual(opening.call_count, 2)
                with self.assertRaises(ValueError):
                    validate_fallback_assets(directory)
                (directory / COVERAGE_FILE).write_text("{}")
                _load_coverage.cache_clear()
                replacement = FallbackFont(self.pg, font.base, 17, bold=False, font_directory=directory)
                self.assertEqual(self.rgba(replacement.render("夜", False, "white")),
                                 self.rgba(font.base.render("夜", False, "white")))
            finally:
                # Windows keeps opened font files locked until both wrappers
                # sharing the base face have released it.
                references = [weakref.ref(adapter) for adapter in (font, replacement) if adapter is not None]
                font = replacement = None
                gc.collect()
                self.assertTrue(all(reference() is None for reference in references))

    def test_repeated_font_quit_and_init_keeps_no_global_sdl_font_handles(self):
        references = []
        for _ in range(3):
            self.pg.font.init()
            font = load_font(self.pg, 23)
            font.render("夜道 श्रद्धा", False, "white")
            references.append(weakref.ref(font))
            del font
            gc.collect()
            self.assertIsNone(references[-1]())
            self.pg.font.quit()
        self.pg.font.init()
        font = load_font(self.pg, 23)
        self.assertGreater(font.render("夜道 श्रद्धा", False, "white").get_width(), 0)
        self.assertLessEqual(_load_coverage.cache_info().currsize, 4)


if __name__ == "__main__":
    unittest.main()
