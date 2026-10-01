import hashlib
import json
from pathlib import Path
import textwrap
import unittest

from PIL import Image

from roads_beneath_shadow import artwork, journey_artwork
from roads_beneath_shadow.lighting import ASCII_RAMP


class JourneyArtworkTests(unittest.TestCase):
    def test_refreshed_orc_encounter_preserves_its_reference_and_nameplate(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["entries"]), 1)
        entry = manifest["entries"][0]
        self.assertEqual(entry["raw_constant"], "ORC_ATTACK_SPRITE")
        source = directory / entry["filename"]
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), entry["source_sha256"])
        body = artwork.ORC_ATTACK_SPRITE.strip("\n")
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), entry["raw_sha256"])
        self.assertIn(textwrap.dedent(body), artwork.ORC_ATTACK_ART)
        self.assertIn("[ ORC ATTACK ]", artwork.ORC_ATTACK_ART)
        self.assertIn("Exactly three", entry["prompt"])
        with Image.open(source) as reference:
            self.assertEqual((reference.format, reference.size), ("PNG", (1536, 1024)))

    def test_references_and_raw_output_match_the_recorded_provenance(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources" / "lanterns"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["converter"]["version"], "1.13.1")
        self.assertEqual(manifest["converter"]["arguments"], ["--dimensions", "72,20", "--map", ASCII_RAMP])
        self.assertEqual(
            {entry["raw_constant"] for entry in manifest["entries"]},
            {"MIDGEWATER_CAMP_ART", "LAST_LANTERN_ART"},
        )
        for entry in manifest["entries"]:
            with self.subTest(scene=entry["scene"]):
                source = directory / entry["filename"]
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), entry["source_sha256"])
                with Image.open(source) as reference:
                    self.assertEqual((reference.format, reference.size, reference.mode), ("PNG", (1536, 1024), "RGB"))
                body = getattr(journey_artwork, entry["raw_constant"]).strip("\n")
                self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), entry["raw_sha256"])
                rows = body.splitlines()
                self.assertTrue(body.isascii())
                self.assertTrue(set(body) <= set(ASCII_RAMP + "\n"))
                self.assertLessEqual(len(rows), 20)
                self.assertLessEqual(max(map(len, rows)), 72)
                self.assertTrue(all(row == row.rstrip() for row in rows))
                self.assertIn("Primary request:", entry["prompt"])
                self.assertTrue(entry["alt_text"])
                self.assertIsInstance(entry["negative"], bool)
