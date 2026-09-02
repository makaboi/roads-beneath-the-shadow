import textwrap
import unittest
from pathlib import Path

from roads_beneath_shadow import artwork


PART_ONE_EXPANSION_ART = (
    "BREE_WAYFARER_ORIGIN_ART",
    "NORTH_ROAD_SCOUT_ORIGIN_ART",
    "HEALERS_APPRENTICE_ORIGIN_ART",
    "CALENOR_LAST_LESSON_ART",
    "EDRIN_DELIVERS_STAR_ART",
    "MARA_DRAWS_BLADES_ART",
    "FIGHT_BESIDE_MARA_ART",
    "HIDDEN_HEARTH_STAR_ART",
    "EDRIN_RANGER_CIPHER_ART",
    "KITCHEN_ESCAPE_ART",
    "ORC_CAPTAIN_PARLEY_ART",
    "CALENOR_LETTER_ART",
    "TOBIN_REED_ARRIVES_ART",
    "EDRINS_ROOM_ART",
    "PONY_PANTRY_CHOICE_ART",
    "MARA_FIRE_CONFESSION_ART",
    "CALENOR_CACHE_CONTENTS_ART",
    "RANGER_TRAIL_MARKS_ART",
    "GHORAK_PRISONER_TRAIL_ART",
    "FLOODED_DITCH_RIDER_ART",
    "CALENOR_BURNING_HOUSE_MEMORY_ART",
    "NED_RETURNS_STAR_RAY_ART",
    "DROWNED_ARMORY_ART",
    "DEAD_ROAD_MOSAIC_ART",
)

LEGACY_CONVERTER_SOURCES = (
    ("title-screen.png", "TITLE_ART_EXPANDED", False),
    ("prancing-pony.png", "PRANCING_PONY_EXTERIOR_STILL", True),
    ("prancing-pony-rain.png", "PRANCING_PONY_EXTERIOR_RAIN_ART", False),
    ("prancing-pony-interior.png", "PRANCING_PONY_INTERIOR_ART", False),
    ("orc-attack.png", "ORC_ATTACK_SPRITE", True),
    ("bree-streets.png", "BREE_STREETS_ART", False),
    ("north-gate.png", "NORTH_GATE_ART", False),
    ("third-stone-discovery.png", "THIRD_STONE_DISCOVERY_ART", False),
    ("star-key-broken.png", "STAR_KEY_BROKEN_ART", False),
    ("star-key-whole.png", "STAR_KEY_WHOLE_ART", False),
    ("midgewater-ruins.png", "MIDGEWATER_RUINS_ART", False),
    ("road-from-bree.png", "ROAD_FROM_BREE_ART", False),
    ("broken-lantern.png", "BROKEN_LANTERN_ART", False),
    ("drowned-watch-post.png", "DROWNED_WATCH_POST_ART", False),
    ("north-wayhouse.png", "NORTH_WAYHOUSE_ART", False),
    ("ancient-road-discovery.png", "ANCIENT_ROAD_DISCOVERY_ART", False),
    ("wayhouse-shrine.png", "WAYHOUSE_SHRINE_ART", False),
    ("orc-tracker.png", "ORC_TRACKER_SPRITE", False),
    ("marsh-warg.png", "MARSH_WARG_SPRITE", False),
    ("ghorak-ash-hand.png", "GHORAK_ASH_HAND_SPRITE", False),
    ("final-ruins-battle.png", "FINAL_RUINS_BATTLE_SPRITE", True),
    ("black-rider-dim.png", "BLACK_RIDER_DIM_SPRITE", False),
    ("black-rider.png", "BLACK_RIDER_SPRITE", True),
)

CONVERTER_SOURCES = LEGACY_CONVERTER_SOURCES + tuple(
    (
        name.removesuffix("_ART").lower().replace("_", "-") + ".png",
        name,
        False,
    )
    for name in PART_ONE_EXPANSION_ART
)

class SparseAsciiSpriteTests(unittest.TestCase):
    def test_sparse_sprite_wrapper_rejects_unportable_or_oversized_art(self) -> None:
        with self.assertRaisesRegex(ValueError, "portable ASCII"):
            artwork._named_ascii_art("orc é", "ORC")
        with self.assertRaisesRegex(ValueError, "72-column"):
            artwork._named_ascii_art("X" * 73, "ORC")
        with self.assertRaisesRegex(ValueError, "72-column"):
            artwork._named_ascii_art("X\tX", "ORC")

    def test_sparse_sprite_bodies_are_unlabeled_and_bounded(self) -> None:
        sprites = (
            (artwork.ORC_ATTACK_SPRITE, "ORC ATTACK"),
            (artwork.ORC_TRACKER_SPRITE, "ORC TRACKER"),
            (artwork.MARSH_WARG_SPRITE, "MARSH WARG"),
            (artwork.GHORAK_ASH_HAND_SPRITE, "GHORAK"),
            (artwork.FINAL_RUINS_BATTLE_SPRITE, "FINAL BATTLE"),
            (artwork.BLACK_RIDER_SPRITE, "BLACK RIDER"),
            (artwork.BLACK_RIDER_DIM_SPRITE, "BLACK RIDER"),
        )
        for sprite, forbidden_label in sprites:
            with self.subTest(label=forbidden_label):
                lines = textwrap.dedent(sprite).strip("\n").splitlines()
                self.assertLessEqual(max(map(len, lines)), 72)
                self.assertLessEqual(len(lines), 20)
                self.assertTrue(sprite.isascii())
                self.assertNotIn(forbidden_label, sprite)

class ArtworkDirectionTests(unittest.TestCase):
    def test_every_public_artwork_uses_the_fixed_compact_stage(self) -> None:
        names = tuple(
            name
            for name in vars(artwork)
            if name == "TITLE_ART_EXPANDED" or name.endswith("_ART")
        )
        self.assertEqual(len(names), 48)
        widths = []
        heights = []
        for name in names:
            with self.subTest(art=name):
                lines = textwrap.dedent(str(getattr(artwork, name))).strip("\n").splitlines()
                body = [line for line in lines if not line.strip().startswith("[")]
                self.assertLessEqual(len(body), 20)
                self.assertLessEqual(max(map(len, body)), 72)
                self.assertTrue(str(getattr(artwork, name)).isascii())
                self.assertTrue(set("".join(body)) <= set(" .:-=+*#@"))
                widths.append(max(map(len, body)))
                heights.append(len(body))
        self.assertGreater(max(widths), 64)
        self.assertGreater(max(heights), 16)

    def test_every_converted_still_has_a_generated_source_png(self) -> None:
        source_dir = Path(__file__).resolve().parents[1] / "assets" / "ascii-sources"
        filenames = tuple(filename for filename, _name, _negative in CONVERTER_SOURCES)
        self.assertEqual({path.name for path in source_dir.glob("*.png")}, set(filenames))
        for filename in filenames:
            with self.subTest(filename=filename):
                source = source_dir / filename
                self.assertTrue(source.is_file(), f"missing generated source: {filename}")
                payload = source.read_bytes()
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertGreater(len(payload), 1024)

    def test_new_story_art_pack_is_compact_and_visually_distinct(self) -> None:
        scenes = [getattr(artwork, name, None) for name in PART_ONE_EXPANSION_ART]
        self.assertTrue(all(isinstance(scene, str) for scene in scenes))
        self.assertEqual(len(scenes), len(set(scenes)))

    def test_star_key_reforging_uses_two_compact_frames(self) -> None:
        animation = getattr(artwork, "STAR_KEY_REFORGED_ART", None)
        self.assertIsInstance(animation, artwork.AnimatedArtwork)
        self.assertEqual(len(animation.frames), 2)
        first = textwrap.dedent(animation.frames[0]).strip("\n").splitlines()
        second = textwrap.dedent(animation.frames[1]).strip("\n").splitlines()
        self.assertNotEqual(first, second)
        self.assertLessEqual(abs(len(first) - len(second)), 1)
        self.assertLessEqual(max(map(len, first)), 72)
        self.assertLessEqual(max(map(len, second)), 72)

    def test_major_scenes_have_room_for_foreground_and_background(self) -> None:
        major_scenes = (
            artwork.TITLE_ART_EXPANDED,
            artwork.PRANCING_PONY_EXTERIOR_ART,
            artwork.PRANCING_PONY_INTERIOR_ART,
            artwork.NORTH_WAYHOUSE_ART,
            artwork.ORC_ATTACK_ART,
            artwork.ORC_TRACKER_INTRO_ART,
            artwork.GHORAK_ASH_HAND_INTRO_ART,
            artwork.FINAL_RUINS_BATTLE_ART,
            artwork.BLACK_RIDER_CLIFFHANGER_ART,
        )
        for scene in major_scenes:
            with self.subTest(opening=scene.strip().splitlines()[0]):
                self.assertGreaterEqual(len(scene.strip("\n").splitlines()), 11)

    def test_character_splashes_use_short_retro_nameplates(self) -> None:
        expected_nameplates = (
            (artwork.ORC_ATTACK_ART, "[ ORC ATTACK ]"),
            (artwork.ORC_TRACKER_INTRO_ART, "[ ORC TRACKER ]"),
            (artwork.MARSH_WARG_INTRO_ART, "[ MARSH WARG ]"),
            (artwork.GHORAK_ASH_HAND_INTRO_ART, "[ GHORAK ASH-HAND ]"),
            (artwork.FINAL_RUINS_BATTLE_ART, "[ FINAL BATTLE ]"),
        )
        for art, nameplate in expected_nameplates:
            with self.subTest(nameplate=nameplate):
                self.assertIn(nameplate, art)
                self.assertLessEqual(len(nameplate), 24)
        for frame in artwork.BLACK_RIDER_CLIFFHANGER_FRAMES:
            self.assertIn("[ BLACK RIDER ]", frame)

    def test_action_art_preserves_structural_landmarks(self) -> None:
        # Public art keeps the same raw silhouettes and adds only a compact
        # title. Human recognition is evaluated separately at rendered size.
        public_pairs = (
            (artwork.ORC_ATTACK_SPRITE, artwork.ORC_ATTACK_ART),
            (artwork.ORC_TRACKER_SPRITE, artwork.ORC_TRACKER_INTRO_ART),
            (artwork.GHORAK_ASH_HAND_SPRITE, artwork.GHORAK_ASH_HAND_INTRO_ART),
            (
                artwork.FINAL_RUINS_BATTLE_SPRITE,
                artwork.FINAL_RUINS_BATTLE_ART,
            ),
        )
        for raw_sprite, public_art in public_pairs:
            with self.subTest(opening=public_art.strip().splitlines()[0]):
                raw_body = textwrap.dedent(raw_sprite).strip("\n")
                self.assertIn(raw_body, public_art)

    def test_animated_accents_have_exactly_two_frames(self) -> None:
        self.assertEqual(len(artwork.PRANCING_PONY_EXTERIOR_FRAMES), 2)
        self.assertEqual(len(artwork.BLACK_RIDER_CLIFFHANGER_FRAMES), 2)
        self.assertEqual(artwork.PRANCING_PONY_EXTERIOR_ART.frames, artwork.PRANCING_PONY_EXTERIOR_FRAMES)
        self.assertEqual(artwork.BLACK_RIDER_CLIFFHANGER_ART.frames, artwork.BLACK_RIDER_CLIFFHANGER_FRAMES)
        self.assertNotEqual(
            artwork.BLACK_RIDER_STAR_DIM_ART,
            artwork.BLACK_RIDER_CLIFFHANGER_STILL,
        )


if __name__ == "__main__":
    unittest.main()
