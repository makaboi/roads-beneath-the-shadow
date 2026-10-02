"""Exercise release diagnostics with the real SDL decoders and damaged assets."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from roads_beneath_shadow import runtime_assets


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is required for native runtime diagnostics")
class RuntimeAssetTests(unittest.TestCase):
    def setUp(self):
        prompt = patch.dict(os.environ, {"PYGAME_HIDE_SUPPORT_PROMPT": "1"})
        prompt.start()
        self.addCleanup(prompt.stop)
        import pygame

        self.pg = pygame
        self.pg.mixer.quit()
        self.font_initialized = self.pg.font.get_init()
        temporary = tempfile.TemporaryDirectory(prefix="rbs decoded assets ")
        self.addCleanup(temporary.cleanup)
        self.package = Path(temporary.name)
        for name in ("pixel_assets", "font_assets", "audio_assets"):
            shutil.copytree(runtime_assets.PACKAGE_DIRECTORY / name, self.package / name)
        self.addCleanup(self.pg.mixer.quit)
        if not self.font_initialized:
            self.addCleanup(self.pg.font.quit)

    def verify(self):
        return runtime_assets.verify_runtime_assets(package_directory=self.package)

    def test_all_native_decoders_work_without_display_or_audible_audio(self):
        display_initialized = self.pg.display.get_init()
        with patch.dict(os.environ, {"SDL_AUDIODRIVER": "rbs-previous-driver"}), patch.object(
            self.pg.display, "init", side_effect=AssertionError("Diagnostic must not initialize a display")
        ), patch.object(self.pg.display, "set_mode", side_effect=AssertionError("Diagnostic must not open a window")):
            report = self.verify()
            self.assertEqual(os.environ["SDL_AUDIODRIVER"], "rbs-previous-driver")
        self.assertEqual(report["world_maps"], 13)
        self.assertEqual(report["fonts"], 2)
        self.assertEqual(report["audio"], 10)
        self.assertEqual(report["audio_driver"], "dummy")
        self.assertGreaterEqual(report["images"], 35)
        self.assertEqual(self.pg.display.get_init(), display_initialized)
        self.assertEqual(self.pg.font.get_init(), self.font_initialized)
        self.assertIsNone(self.pg.mixer.get_init())

    def test_damaged_png_fails_with_its_filename(self):
        (self.package / "pixel_assets/title.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        with self.assertRaisesRegex(ValueError, r"decode title\.png"):
            self.verify()
        self.assertIsNone(self.pg.mixer.get_init())

    def test_wrong_motion_atlas_dimensions_cannot_silently_use_fallback_sprites(self):
        self.pg.image.save(self.pg.Surface((20, 24)), str(self.package / "pixel_assets/world-motion.png"))
        with self.assertRaisesRegex(ValueError, r"world-motion\.png.*geometry"):
            self.verify()

    def test_missing_battle_background_fails_instead_of_using_the_previous_story_subject(self):
        (self.package / "pixel_assets/echo-bridge-battle.png").unlink()
        with self.assertRaisesRegex(ValueError, r"missing: echo-bridge-battle\.png"):
            self.verify()

    def test_wrong_battle_background_geometry_is_rejected_by_the_native_decoder(self):
        self.pg.image.save(self.pg.Surface((320, 180)), str(self.package / "pixel_assets/echo-bridge-battle.png"))
        with self.assertRaisesRegex(ValueError, r"echo-bridge-battle\.png.*geometry"):
            self.verify()

    def test_missing_contextual_scene_cannot_silently_use_an_unrelated_illustration(self):
        (self.package / "pixel_assets/hall-of-eight.png").unlink()
        with self.assertRaisesRegex(ValueError, r"missing: hall-of-eight\.png"):
            self.verify()

    def test_missing_authored_cast_is_rejected_even_when_the_game_can_use_legacy_sprites(self):
        (self.package / "pixel_assets/world-battle-cast.png").unlink()
        with self.assertRaisesRegex(ValueError, r"missing: world-battle-cast\.png"):
            self.verify()

    def test_wrong_authored_portrait_geometry_is_rejected(self):
        self.pg.image.save(self.pg.Surface((191, 80)), str(self.package / "pixel_assets/world-origin-portraits.png"))
        with self.assertRaisesRegex(ValueError, r"world-origin-portraits\.png.*geometry"):
            self.verify()

    def test_damaged_ttf_cannot_silently_use_a_system_font(self):
        (self.package / "font_assets/DejaVuSansMono.ttf").write_bytes(b"damaged font")
        with patch.dict(os.environ, {"SDL_AUDIODRIVER": "rbs-previous-driver"}), self.assertRaisesRegex(ValueError, r"decode DejaVuSansMono\.ttf"):
            self.verify()
        self.assertEqual(self.pg.font.get_init(), self.font_initialized)
        self.assertIsNone(self.pg.mixer.get_init())

    def test_damaged_wav_cannot_silently_disable_released_sound(self):
        (self.package / "audio_assets/victory.wav").write_bytes(b"damaged sound")
        with patch.dict(os.environ, {"SDL_AUDIODRIVER": "rbs-previous-driver"}):
            with self.assertRaisesRegex(ValueError, r"decode victory\.wav"):
                self.verify()
            self.assertEqual(os.environ["SDL_AUDIODRIVER"], "rbs-previous-driver")
        self.assertIsNone(self.pg.mixer.get_init())

    def test_missing_depth_layer_fails_instead_of_rendering_a_flat_fallback(self):
        (self.package / "pixel_assets/world-depth.png").unlink()
        with self.assertRaisesRegex(ValueError, r"missing: world-depth\.png"):
            self.verify()

    def test_diagnostic_preserves_an_already_initialized_font_module(self):
        self.pg.font.init()
        try:
            self.verify()
            self.assertTrue(self.pg.font.get_init())
        finally:
            if not self.font_initialized:
                self.pg.font.quit()

    def test_active_audio_is_preserved_instead_of_replaced_with_dummy(self):
        with patch.dict(os.environ, {"SDL_AUDIODRIVER": "dummy"}):
            self.pg.mixer.init(frequency=16_000, size=-16, channels=2)
            original_format = self.pg.mixer.get_init()
            with self.assertRaisesRegex(RuntimeError, "before game audio"):
                self.verify()
            self.assertEqual(self.pg.mixer.get_init(), original_format)

    def test_fonts_are_released_before_subsystem_shutdown_and_later_errors(self):
        original_font = self.pg.font.Font
        original_quit = self.pg.font.quit
        live = set()
        lifecycle = []

        class TrackedFont:
            def __init__(instance, *args):
                instance.font = original_font(*args)
                live.add(id(instance))

            def render(instance, *args):
                return instance.font.render(*args)

            def __del__(instance):
                instance.font = None
                live.discard(id(instance))
                lifecycle.append("released")

        def quit_after_release():
            self.assertFalse(live, "A native Font would keep its TTF open across subsystem shutdown")
            lifecycle.append("quit")
            original_quit()

        for damaged_audio in (False, True):
            with self.subTest(damaged_audio=damaged_audio):
                original_quit()
                if damaged_audio:
                    (self.package / "audio_assets/victory.wav").write_bytes(b"damaged sound")
                with patch.object(self.pg.font, "Font", TrackedFont), patch.object(self.pg.font, "quit", side_effect=quit_after_release):
                    if damaged_audio:
                        with self.assertRaisesRegex(ValueError, r"decode victory\.wav"):
                            self.verify()
                    else:
                        self.verify()
                self.assertEqual(lifecycle[-3:], ["released", "released", "quit"])
        if self.font_initialized:
            self.pg.font.init()

    def test_decoded_font_files_can_be_deleted_immediately(self):
        self.pg.font.quit()
        self.verify()
        for path in (self.package / "font_assets").glob("*.ttf"):
            path.unlink()
        if self.font_initialized:
            self.pg.font.init()


class RuntimeManifestTests(unittest.TestCase):
    def manifest(self):
        return json.loads((runtime_assets.PACKAGE_DIRECTORY / "pixel_assets/manifest.json").read_text())

    def test_original_manifests_remain_valid_without_the_optional_visual_categories(self):
        manifest = self.manifest()
        manifest.pop("additional_scenes")
        manifest.pop("sprite_sheets")
        expected = runtime_assets.expected_image_sizes(manifest)
        self.assertEqual(expected["world-motion.png"], (160, 4224))
        self.assertEqual(expected["title.png"], (320, 240))
        self.assertNotIn("world-battle-cast.png", expected)

    def test_invalid_additional_scene_names_cannot_escape_the_asset_directory(self):
        for name in ("../hall-of-eight", "/hall-of-eight", "hall.png", True):
            manifest = self.manifest()
            manifest["additional_scenes"] = [name]
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "invalid pixel scene names"):
                runtime_assets.expected_image_sizes(manifest)

    def test_sprite_sheet_geometry_requires_positive_integer_dimensions_and_safe_names(self):
        for sheets in ([], {"../cast": [40, 48]}, {"world-cast": [True, 48]},
                       {"world-cast": [0, 48]}, {"world-cast": [40.5, 48]},
                       {"world-cast": [40]}, {"world-cast": "40x48"}):
            manifest = self.manifest()
            manifest["sprite_sheets"] = sheets
            with self.subTest(sheets=sheets), self.assertRaisesRegex(ValueError, "invalid sprite sheet geometry"):
                runtime_assets.expected_image_sizes(manifest)


if __name__ == "__main__":
    unittest.main()
