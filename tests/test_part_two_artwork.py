from __future__ import annotations
import json
from pathlib import Path
import textwrap
import unittest

from PIL import Image

import roads_beneath_shadow.part_two_artwork as part_two_artwork
from roads_beneath_shadow.artwork import AnimatedArtwork

SOURCE_DIR = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources" / "part-two"
MANIFEST_PATH = SOURCE_DIR / "manifest.json"
EXPECTED_CONVERTER = {"executable": "/opt/homebrew/bin/ascii-image-converter", "version": "1.13.1", "arguments": ["--dimensions", "72,20", "--map", " .:-=+*#@"], "cleanup": ["outer_blank_rows", "trailing_whitespace"]}

NAMEPLATES = {
    "RIDER_PURSUIT_INTRO_ART": ("RIDER_PURSUIT_INTRO_SPRITE", "BLACK RIDER"),
    "ORC_SAPPER_INTRO_ART": ("ORC_SAPPER_INTRO_SPRITE", "ORC SAPPER"),
    "CHAIN_TROLL_INTRO_ART": ("CHAIN_TROLL_INTRO_SPRITE", "CHAIN TROLL"),
    "FALSE_RANGER_DUEL_ART": ("FALSE_RANGER_DUEL_SPRITE", "FALSE RANGER"),
    "RIDER_FINAL_ENTRANCE_ART": ("RIDER_FINAL_ENTRANCE_SPRITE", "BLACK RIDER"),
    "FINAL_SEAL_BATTLE_ART": ("FINAL_SEAL_BATTLE_SPRITE", "FINAL SEAL"),
}


class PartTwoArtworkTests(unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_every_manifest_source_is_a_valid_png(self) -> None:
        manifest = self._manifest()
        self.assertEqual(set(manifest), {"converter", "entries"})
        self.assertEqual(manifest["converter"], EXPECTED_CONVERTER)
        entries = manifest["entries"]
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 42)
        self.assertEqual(len({e["filename"] for e in entries}), 42)
        self.assertEqual(len({e["raw_constant"] for e in entries}), 42)
        self.assertEqual(len({e["public_art"] for e in entries}), 40)
        self.assertEqual(len({e["alt_text"] for e in entries}), 40)
        self.assertEqual(
            {path.name for path in SOURCE_DIR.glob("*.png")},
            {entry["filename"] for entry in entries},
        )
        for order, entry in enumerate(entries, 1):
            with self.subTest(order=order, filename=entry["filename"]):
                self.assertEqual(set(entry), {"filename", "raw_constant", "public_art", "scene", "alt_text", "negative", "prompt"})
                self.assertIsInstance(entry["negative"], bool)
                self.assertTrue(entry["scene"])
                self.assertTrue(entry["alt_text"])
                prompt = entry["prompt"]
                for label in (
                    "Use case:",
                    "Asset type:",
                    "Primary request:",
                    "Scene/backdrop:",
                    "Subject:",
                    "Style/medium:",
                    "Composition/framing:",
                    "Lighting/mood:",
                    "Color palette:",
                    "Constraints:",
                ):
                    self.assertIn(label, prompt)
                self.assertIn("Avoid", prompt)
                source_path = SOURCE_DIR / entry["filename"]
                self.assertGreater(source_path.stat().st_size, 1024)
                with Image.open(source_path) as source:
                    self.assertEqual(source.format, "PNG")
                    self.assertEqual(source.size, (1536, 1024))
                    self.assertEqual(source.mode, "RGB")

    def test_public_art_and_raw_constant_contract(self) -> None:
        entries = self._manifest()["entries"]
        public_names = {name for name in vars(part_two_artwork) if name.endswith("_ART")}
        raw_names = [entry["raw_constant"] for entry in entries]

        self.assertEqual(public_names, {entry["public_art"] for entry in entries})
        self.assertEqual(len(public_names), 40)
        self.assertEqual(len(raw_names), len(set(raw_names)))
        self.assertEqual(sum(name.endswith("_ART") for name in raw_names), 32)
        self.assertEqual(sum(name.endswith("_SPRITE") for name in raw_names), 6)
        self.assertEqual(sum(name.endswith("_FRAME") for name in raw_names), 4)
        self.assertTrue(all(hasattr(part_two_artwork, name) for name in raw_names))

        wrapped_raw = {
            entry["raw_constant"]
            for entry in entries
            if entry["raw_constant"] != entry["public_art"]
        }
        self.assertEqual(
            wrapped_raw,
            {raw_name for raw_name, _title in NAMEPLATES.values()}
            | {
                "WALL_NAMES_DIM_FRAME",
                "WALL_NAMES_LIT_FRAME",
                "FORNOST_MAP_DIM_FRAME",
                "FORNOST_MAP_LIT_FRAME",
            },
        )

    def test_raw_art_is_portable_and_within_terminal_stage(self) -> None:
        for entry in self._manifest()["entries"]:
            with self.subTest(raw_constant=entry["raw_constant"]):
                raw = getattr(part_two_artwork, entry["raw_constant"])
                body = raw.strip("\n")
                lines = body.splitlines()
                self.assertTrue(body)
                self.assertTrue(all(character == "\n" or " " <= character <= "~" for character in body))
                self.assertLessEqual(len(lines), 20)
                self.assertLessEqual(max(map(len, lines)), 72)

    def test_animations_have_exactly_two_distinct_raw_frames(self) -> None:
        expected = {
            "WALL_NAMES_AWAKENING_ART": ("WALL_NAMES_DIM_FRAME", "WALL_NAMES_LIT_FRAME"),
            "FORNOST_MAP_CLIFFHANGER_ART": ("FORNOST_MAP_DIM_FRAME", "FORNOST_MAP_LIT_FRAME"),
        }
        public_names = {name for name in vars(part_two_artwork) if name.endswith("_ART")}
        self.assertEqual(
            {name for name in public_names if isinstance(getattr(part_two_artwork, name), AnimatedArtwork)},
            set(expected),
        )
        for public_name, (dim_name, lit_name) in expected.items():
            with self.subTest(public_art=public_name):
                animation = getattr(part_two_artwork, public_name)
                dim = getattr(part_two_artwork, dim_name)
                lit = getattr(part_two_artwork, lit_name)
                self.assertIsInstance(animation, AnimatedArtwork)
                self.assertEqual(str(animation), lit)
                self.assertEqual(animation.frames, (dim, lit))
                self.assertEqual(len(animation.frames), 2)
                self.assertEqual(len(set(animation.frames)), 2)

    def test_nameplates_are_the_exact_six_wrappers(self) -> None:
        for public_name, (raw_name, title) in NAMEPLATES.items():
            with self.subTest(public_art=public_name):
                self.assertTrue(raw_name.endswith("_SPRITE"))
                body = textwrap.dedent(getattr(part_two_artwork, raw_name)).strip("\n")
                width = max(map(len, body.splitlines()))
                expected = "\n" + f"[ {title} ]".center(width) + "\n" + body + "\n"
                self.assertEqual(getattr(part_two_artwork, public_name), expected)

if __name__ == "__main__":
    unittest.main()
