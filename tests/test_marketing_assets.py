import unittest
from pathlib import Path

from PIL import Image

from scripts.generate_marketing_assets import SCENES

ROOT = Path(__file__).resolve().parents[1]


class MarketingArtworkTests(unittest.TestCase):
    def test_demo_uses_curated_six_scene_sequence(self) -> None:
        self.assertEqual(
            tuple(scene[0] for scene in SCENES),
            (
                "THE SILVER STAR",
                "ARRIVAL AT THE INN",
                "ORCS AT THE DOOR",
                "THE BLACK RIDER",
                "THE FINAL SEAL BATTLE",
                "BENEATH RUINED FORNOST",
            ),
        )

    def test_generated_assets_have_exact_frame_counts_and_dimensions(self) -> None:
        with Image.open(ROOT / "assets" / "gameplay-demo.gif") as demo:
            self.assertEqual(demo.n_frames, 18)
            self.assertEqual(demo.size, (960, 600))


if __name__ == "__main__":
    unittest.main()
