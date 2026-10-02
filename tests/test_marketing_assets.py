import unittest
from pathlib import Path

from PIL import Image

from scripts.generate_marketing_assets import SCENES, font

ROOT = Path(__file__).resolve().parents[1]


class MarketingArtworkTests(unittest.TestCase):
    def test_demo_includes_both_lantern_scenes_in_story_order(self) -> None:
        self.assertEqual(
            tuple(scene[0] for scene in SCENES),
            (
                "THE SILVER STAR",
                "ARRIVAL AT THE INN",
                "ORCS AT THE DOOR",
                "A FIRE WITHOUT FLAME",
                "THE MARSH WARG",
                "GHORAK ASH-HAND",
                "THE RUINED GATEWAY",
                "THE BLACK RIDER",
                "THE LAST LANTERN",
                "THE FINAL SEAL BATTLE",
                "BENEATH RUINED FORNOST",
            ),
        )

    def test_generated_assets_have_exact_frame_counts_and_dimensions(self) -> None:
        with Image.open(ROOT / "assets" / "gameplay-demo.gif") as demo:
            self.assertEqual(demo.n_frames, 33)
            self.assertEqual(demo.size, (960, 600))

    def test_preview_font_resolves_to_a_monospaced_face_on_this_platform(self) -> None:
        face = font(16)
        self.assertAlmostEqual(face.getlength("MMMM"), face.getlength("iiii"))


if __name__ == "__main__":
    unittest.main()
