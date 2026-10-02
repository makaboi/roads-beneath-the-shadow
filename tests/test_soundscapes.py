"""Original score integrity and real SDL playback under the dummy audio driver."""

from array import array
import contextlib
import importlib.util
import io
import math
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import wave

from roads_beneath_shadow.soundscapes import (
    AUDIO_DIRECTORY, FADE_SECONDS, SoundscapePlayer, TRACKS,
    _effect_wave, soundscape_for_scene,
)


class SoundscapeAssetTests(unittest.TestCase):
    def test_all_original_loops_have_headroom_stereo_and_matching_endpoints(self):
        total_size = 0
        for scene, filename in TRACKS.items():
            path = AUDIO_DIRECTORY / filename
            with self.subTest(scene=scene), wave.open(str(path), "rb") as source:
                self.assertEqual(source.getnchannels(), 2)
                self.assertEqual(source.getsampwidth(), 2)
                self.assertEqual(source.getframerate(), 16_000)
                self.assertEqual(source.getnframes(), 320_000)
                samples = array("h", source.readframes(source.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
                self.assertEqual(samples[:2], samples[-2:])
                self.assertGreater(max(abs(value) for value in samples), 900)
                self.assertLess(max(abs(value) for value in samples), 10_000)
                self.assertLess(abs(sum(samples) / len(samples)), 50)
                self.assertTrue(any(samples[i] != samples[i + 1] for i in range(0, len(samples), 2)))
                self.assertTrue(all(math.isfinite(value) for value in samples))
            total_size += path.stat().st_size
        self.assertLess(total_size, 7 * 1024 * 1024)

    def test_generator_reproduces_the_same_material_without_external_libraries(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "generate_soundscapes.py"
        spec = importlib.util.spec_from_file_location("original_soundscape_generator", path)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        for scene in generator.SCENES:
            with self.subTest(scene=scene):
                first = generator.generate_track(scene, sample_rate=400, duration=20.0)
                second = generator.generate_track(scene, sample_rate=400, duration=20.0)
                self.assertEqual(first, second)
                self.assertEqual(len(first), 16_000)
                self.assertEqual(first[:2], first[-2:])
        with self.assertRaises(ValueError):
            generator.generate_track("unknown")

    def test_effects_are_short_quiet_and_deterministic(self):
        for effect in ("footstep", "interact", "hover"):
            with self.subTest(effect=effect):
                data = _effect_wave(effect)
                self.assertEqual(data, _effect_wave(effect))
                with wave.open(io.BytesIO(data), "rb") as source:
                    self.assertEqual(source.getnchannels(), 2)
                    self.assertLess(source.getnframes() / source.getframerate(), 0.2)
                    samples = array("h", source.readframes(source.getnframes()))
                    self.assertLess(max(abs(value) for value in samples), 3_000)
                    self.assertEqual(samples[:2], array("h", [0, 0]))

    def test_world_and_story_scenes_choose_their_score(self):
        for scene in ("pony", "chapter1_decision", "branch_escape", "tavern-interior"):
            self.assertEqual(soundscape_for_scene(scene), "tavern")
        for scene in ("bree", "north_gate", "road_from_bree", "marsh", "camp"):
            self.assertEqual(soundscape_for_scene(scene), "outdoors")
        for scene in ("wayhouse", "hall", "part2_descent", "part2_last_seal", "seal"):
            self.assertEqual(soundscape_for_scene(scene), "buried")
        for scene in ("lantern", "part2_vigil", "complete"):
            self.assertEqual(soundscape_for_scene(scene), "lantern")
        for scene in (None, "", "menu", "MAIN MENU", "title", "pause"):
            self.assertIsNone(soundscape_for_scene(scene))
        self.assertEqual(soundscape_for_scene("pony", combat=True), "combat")


class SoundscapeMixerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pygame
        except ImportError:
            raise unittest.SkipTest("pygame-ce is optional in terminal-only test runs")
        cls.pg = pygame

    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"SDL_AUDIODRIVER": "dummy"})
        self.environment.start()
        self.pg.mixer.quit()
        self.player = SoundscapePlayer(self.pg)

    def tearDown(self):
        self.player.stop()
        self.pg.mixer.quit()
        self.environment.stop()

    def test_construction_and_muted_updates_do_not_open_a_device(self):
        self.assertIsNone(self.pg.mixer.get_init())
        self.player.set_scene("pony")
        self.player.update(1.0, enabled=False)
        self.assertIsNone(self.pg.mixer.get_init())
        self.assertFalse(self.player.play_effect("interact"))

    def test_scene_changes_crossfade_on_two_channels_and_menu_suspends(self):
        self.player.set_scene("pony")
        self.player.update(FADE_SECONDS)
        first = next(voice for voice in self.player._voices if voice.track == "tavern")
        self.assertTrue(first.channel.get_busy())
        self.assertAlmostEqual(first.gain, 1.0)
        self.player.set_scene("wayhouse")
        self.player.update(FADE_SECONDS / 2)
        second = next(voice for voice in self.player._voices if voice.track == "buried")
        self.assertTrue(first.channel.get_busy())
        self.assertTrue(second.channel.get_busy())
        self.assertAlmostEqual(first.gain, 0.5)
        self.assertAlmostEqual(second.gain, 0.5)
        self.player.update(FADE_SECONDS / 2)
        self.assertFalse(first.channel.get_busy())
        self.assertIsNone(first.track)
        self.assertAlmostEqual(second.gain, 1.0)
        self.player.set_scene(None)
        self.player.update(FADE_SECONDS)
        self.assertFalse(any(voice.channel.get_busy() for voice in self.player._voices))

    def test_toggle_mute_is_immediate_and_restores_the_selected_scene(self):
        self.player.set_scene("hall")
        self.player.update(FADE_SECONDS)
        self.assertTrue(self.player.play_effect("interact"))
        self.player.update(0.001, enabled=False)
        self.assertEqual(self.player.scene, "buried")
        self.assertFalse(any(voice.channel.get_busy() for voice in self.player._voices))
        self.assertFalse(self.player._effect_channel.get_busy())
        self.player.update(FADE_SECONDS, enabled=True)
        self.assertTrue(any(voice.channel.get_busy() for voice in self.player._voices))
        self.assertEqual(len(self.player._sounds), 1)

    def test_rapid_room_changes_and_combat_never_need_a_third_music_channel(self):
        for scene in ("pony", "bree", "hall", "lantern", "pony"):
            self.player.set_scene(scene)
            self.player.update(0.15)
            self.assertEqual(len(self.player._voices), 2)
        self.player.set_scene("pony", combat=True)
        self.player.update(FADE_SECONDS)
        self.assertEqual(self.player.scene, "combat")
        self.assertEqual([voice.track for voice in self.player._voices if voice.track], ["combat"])
        self.assertLessEqual(len(self.player._sounds), 5)

    def test_effects_obey_cooldown_unknown_effect_and_menu_suspension(self):
        self.player.set_scene("pony")
        self.player.update(FADE_SECONDS)
        self.assertTrue(self.player.play_effect("hover"))
        self.assertFalse(self.player.play_effect("hover"))
        self.player.update(0.17)
        self.assertTrue(self.player.play_effect("hover"))
        self.assertFalse(self.player.play_effect("unknown"))
        self.player.set_scene(None)
        self.assertFalse(self.player.play_effect("interact"))

    def test_device_failure_and_missing_assets_are_safe_fallbacks(self):
        self.player.set_scene("pony")
        with mock.patch.object(self.pg.mixer, "init", side_effect=self.pg.error("No device")):
            self.player.update(1.0)
        self.assertFalse(self.player.available)
        self.assertFalse(self.player.play_effect("interact"))
        self.player = SoundscapePlayer(self.pg, Path("/missing-original-score"))
        self.player.set_scene("pony")
        self.player.update(1.0)
        self.assertIsNone(self.pg.mixer.get_init())

    def test_volumes_are_clamped_and_stop_leaves_unrelated_channels_alone(self):
        self.player.set_scene("pony")
        self.player.update(FADE_SECONDS, music_volume=5.0, sfx_volume=float("nan"))
        voice = next(voice for voice in self.player._voices if voice.track)
        self.assertAlmostEqual(voice.channel.get_volume(), 1.0, places=2)
        self.assertFalse(self.player.play_effect("hover"))
        cue = self.pg.mixer.Sound(str(AUDIO_DIRECTORY / "notice.wav"))
        cue_channel = self.pg.mixer.Channel(3)
        cue_channel.play(cue, loops=-1)
        self.player.stop()
        self.assertTrue(cue_channel.get_busy())
        self.assertIsNotNone(self.pg.mixer.get_init())


if __name__ == "__main__":
    unittest.main()
