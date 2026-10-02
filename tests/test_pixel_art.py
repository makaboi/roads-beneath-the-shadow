"""Every scene the story can display must ship in the graphical package."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from roads_beneath_shadow import artwork, journey_artwork, part_two_artwork, pixel_art
from scripts import generate_pixel_assets


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

    def test_contextual_journey_illustrations_keep_their_story_subjects(self):
        expected = (
            (journey_artwork.MIDGEWATER_CAMP_ART, "midgewater-camp"),
            (part_two_artwork.HALL_EIGHT_WARDENS_ART, "hall-of-eight"),
            (part_two_artwork.ERASED_EIGHTH_STATUE_ART, "hall-of-eight"),
            (part_two_artwork.ECHO_BRIDGE_ART, "echo-bridge"),
            (part_two_artwork.DROWNED_CARAVAN_ART, "drowned-mile"),
            (part_two_artwork.PRISONERS_IRON_CAGES_ART, "sluice-prison"),
            (part_two_artwork.HOUSE_UNDER_ASH_ART, "house-under-ash"),
            (journey_artwork.LAST_LANTERN_ART, "last-lantern-scene"),
            (artwork.CALENOR_BURNING_HOUSE_MEMORY_ART, "burning-house-memory"),
            (part_two_artwork.FALSE_RANGER_DUEL_ART, "false-ranger-duel"),
        )
        for illustration, subject in expected:
            with self.subTest(subject=subject):
                self.assertEqual(pixel_art.resolve_scene(illustration).stem, subject)

    def test_authored_asset_provenance_matches_packaged_bytes(self):
        manifest = json.loads((pixel_art.ASSET_DIR / "manifest.json").read_text())
        for category in ("scene_sources", "battle_background_sources", "sprite_sheet_sources"):
            for name, metadata in manifest[category].items():
                with self.subTest(category=category, scene=name):
                    asset = pixel_art.ASSET_DIR / f"{name}.png"
                    self.assertEqual(metadata["native_sha256"], hashlib.sha256(asset.read_bytes()).hexdigest())
                    self.assertRegex(metadata["source_sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(Path(metadata["source_name"]).name, metadata["source_name"])
                    self.assertTrue((Path(__file__).resolve().parents[1] / metadata["conversion"]["script"]).is_file())

    def test_authored_sprite_sheets_preserve_binary_alpha_and_native_geometry(self):
        manifest = json.loads((pixel_art.ASSET_DIR / "manifest.json").read_text())
        for name, dimensions in manifest["sprite_sheets"].items():
            with self.subTest(sheet=name), Image.open(pixel_art.ASSET_DIR / f"{name}.png") as sheet:
                self.assertEqual(sheet.size, tuple(dimensions))
                rgba = sheet.convert("RGBA")
                pixels = rgba.tobytes()
                self.assertTrue(set(pixels[3::4]) <= {0, 255})
                visible = {pixels[index:index + 3] for index in range(0, len(pixels), 4) if pixels[index + 3]}
                self.assertLessEqual(len(visible), 32)

    def test_standalone_background_build_preserves_existing_assets_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            destination = directory / "pixel_assets"
            destination.mkdir()
            original_manifest = json.loads((pixel_art.ASSET_DIR / "manifest.json").read_text())
            (destination / "manifest.json").write_text(json.dumps(original_manifest))
            protected = ("title.png", "map.png", "broken-key.png", "world-motion.png")
            for name in protected:
                (destination / name).write_bytes(b"existing asset: " + name.encode())
            source = directory / "generated-source.png"
            image = Image.new("RGB", (96, 72))
            image.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256) for y in range(72) for x in range(96)])
            image.save(source)
            source_bytes = source.read_bytes()
            with patch.object(generate_pixel_assets, "DEST", destination), patch.object(
                generate_pixel_assets, "draw_props", side_effect=AssertionError("A standalone background must not rebuild props")
            ), patch("sys.argv", ["generate_pixel_assets.py", "--battle-background", f"test-bridge={source}", "--source-date", "2026-10-02"]):
                generate_pixel_assets.main()
            self.assertEqual(source.read_bytes(), source_bytes)
            for name in protected:
                self.assertEqual((destination / name).read_bytes(), b"existing asset: " + name.encode())
            manifest = json.loads((destination / "manifest.json").read_text())
            self.assertEqual(manifest["environment_scenes"], original_manifest["environment_scenes"])
            self.assertEqual(manifest["encounter_scenes"], original_manifest["encounter_scenes"])
            self.assertEqual(len(manifest["environment_scenes"]), 6)
            self.assertEqual(len(manifest["encounter_scenes"]), 6)
            self.assertIn("test-bridge", manifest["battle_backgrounds"])
            metadata = manifest["battle_background_sources"]["test-bridge"]
            self.assertEqual(metadata["source_sha256"], hashlib.sha256(source_bytes).hexdigest())
            self.assertEqual(metadata["source_dimensions"], [96, 72])
            self.assertEqual(metadata["generated_on"], "2026-10-02")
            built = destination / "test-bridge.png"
            self.assertEqual(metadata["native_sha256"], hashlib.sha256(built.read_bytes()).hexdigest())
            with Image.open(built) as background:
                self.assertEqual(background.size, (320, 240))
                self.assertIsNotNone(background.convert("RGB").getcolors(maxcolors=32))

    def test_background_conversion_cannot_overwrite_fixed_atlas_or_world_names(self):
        import argparse
        for name in ("title", "ranger", "broken-key", "world-motion"):
            with self.subTest(name=name), self.assertRaises(argparse.ArgumentTypeError):
                generate_pixel_assets.background_source(f"{name}=source.png")
