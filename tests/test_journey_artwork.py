import hashlib
import json
from pathlib import Path
import textwrap
import unittest

from PIL import Image

from roads_beneath_shadow import artwork, journey_artwork, part_two_artwork
from roads_beneath_shadow.lighting import ASCII_RAMP


class JourneyArtworkTests(unittest.TestCase):
    def test_refreshed_orc_encounter_preserves_its_reference_and_nameplate(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["entries"] if item["raw_constant"] == "ORC_ATTACK_SPRITE")
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

    def test_all_refreshed_scenes_preserve_their_source_and_raw_checksums(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {entry["raw_constant"] for entry in manifest["entries"]},
            {
                "ORC_ATTACK_SPRITE", "TITLE_ART_EXPANDED",
                "PRANCING_PONY_EXTERIOR_STILL", "PRANCING_PONY_EXTERIOR_DIM_ART",
                "BLACK_RIDER_SPRITE", "BLACK_RIDER_DIM_SPRITE",
                "MARSH_WARG_SPRITE", "GHORAK_ASH_HAND_SPRITE",
                "FINAL_RUINS_BATTLE_SPRITE", "FINAL_SEAL_BATTLE_SPRITE",
            },
        )
        for entry in manifest["entries"]:
            with self.subTest(scene=entry["scene"], raw=entry["raw_constant"]):
                module = part_two_artwork if entry.get("module") == "part_two_artwork" else artwork
                source = directory / entry["filename"]
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), entry["source_sha256"])
                body = getattr(module, entry["raw_constant"]).strip("\n")
                self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), entry["raw_sha256"])
                with Image.open(source) as reference:
                    self.assertEqual((reference.format, reference.size, reference.mode), ("PNG", (1536, 1024), "RGB"))
                self.assertTrue(set(body) <= set(ASCII_RAMP + "\n"))
                self.assertLessEqual(len(body.splitlines()), 20)
                self.assertLessEqual(max(map(len, body.splitlines())), 72)
                self.assertTrue(entry["alt_text"])
                if "reference_filename" in entry:
                    self.assertIn("illumination only", entry["prompt"])
                    self.assertTrue((directory / entry["reference_filename"]).is_file())
                else:
                    self.assertIn("Primary request:", entry["prompt"])

    def test_inn_and_rider_light_frames_preserve_the_same_silhouette(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources"
        for dim, lit, animation in (
            ("prancing-pony-dim.png", "prancing-pony.png", artwork.PRANCING_PONY_EXTERIOR_ART),
            ("black-rider-dim.png", "black-rider.png", artwork.BLACK_RIDER_CLIFFHANGER_ART),
        ):
            with self.subTest(scene=lit):
                with Image.open(directory / dim) as reference:
                    dim_mask = [value > 60 for value in reference.convert("L").get_flattened_data()]
                with Image.open(directory / lit) as reference:
                    lit_mask = [value > 110 for value in reference.convert("L").get_flattened_data()]
                intersection = sum(a and b for a, b in zip(dim_mask, lit_mask))
                union = sum(a or b for a, b in zip(dim_mask, lit_mask))
                self.assertGreater(intersection / union, 0.99)
                staged_heights = {
                    len(frame.strip("\n").splitlines()) + offset
                    for frame, offset in zip(animation.frames, animation.frame_offsets)
                }
                self.assertEqual(len(staged_heights), 1)
                self.assertEqual(str(animation), animation.frames[-1])

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
