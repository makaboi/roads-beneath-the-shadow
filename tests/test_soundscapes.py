"""Original score integrity and real SDL playback under the dummy audio driver."""

from array import array
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
    AUDIO_DIRECTORY, BATTLE_EFFECTS, FADE_SECONDS, RETRY_SECONDS, SoundscapePlayer, TRACKS,
    _effect_wave, soundscape_for_scene,
)


class SoundscapeAssetTests(unittest.TestCase):
    def test_all_original_loops_have_headroom_stereo_and_matching_endpoints(self):
        total_size = 0
        loudness = []
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
                rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
                db = 20 * math.log10(rms)
                self.assertGreater(db, -27)
                self.assertLess(db, -22)
                loudness.append(db)
            total_size += path.stat().st_size
        self.assertLess(total_size, 7 * 1024 * 1024)
        self.assertLess(max(loudness) - min(loudness), 3.2)

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

    def test_full_volume_music_crossfade_and_two_cues_leave_mixer_headroom(self):
        from roads_beneath_shadow.audio import SoundPlayer
        def peak(path):
            with wave.open(str(path), "rb") as source:
                samples = array("h", source.readframes(source.getnframes()))
                return max(map(abs, samples)) / 32768
        music = max(peak(AUDIO_DIRECTORY / name) for name in TRACKS.values())
        cue = max(peak(AUDIO_DIRECTORY / name) for name in SoundPlayer.CUES.values())
        effects = []
        for name in ("footstep", "interact", "hover", *BATTLE_EFFECTS):
            with wave.open(io.BytesIO(_effect_wave(name)), "rb") as source:
                effects.append(max(map(abs, array("h", source.readframes(source.getnframes())))) / 32768)
        # Equal-power music has at most sqrt(2) combined gain. This bound uses
        # coincident waveform peaks, both cue channels and effects at 100%,
        # and no ducking: even that deliberately pessimistic mix stays clean.
        self.assertLess(music * math.sqrt(2) + cue * 2 + max(effects), 0.95)

    def test_battle_reactions_are_distinct_short_quiet_and_click_free(self):
        fingerprints = set()
        for effect, duration in BATTLE_EFFECTS.items():
            with self.subTest(effect=effect):
                data = _effect_wave(effect)
                self.assertEqual(data, _effect_wave(effect))
                fingerprints.add(data)
                with wave.open(io.BytesIO(data), "rb") as source:
                    self.assertEqual(source.getnchannels(), 2)
                    self.assertEqual(source.getsampwidth(), 2)
                    self.assertAlmostEqual(source.getnframes() / source.getframerate(), duration, places=4)
                    samples = array("h", source.readframes(source.getnframes()))
                    self.assertEqual(samples[:2], array("h", [0, 0]))
                    self.assertEqual(samples[-2:], array("h", [0, 0]))
                    self.assertLessEqual(max(map(abs, samples)), round(0.08 * 32768))
                    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
                    self.assertGreater(rms, 0.017)
                    self.assertLessEqual(rms, 10 ** (-32 / 20) + 0.0001)
        self.assertEqual(len(fingerprints), len(BATTLE_EFFECTS))

    def test_world_and_story_scenes_choose_their_score(self):
        for scene in ("pony", "chapter1_decision", "branch_escape", "tavern-interior"):
            self.assertEqual(soundscape_for_scene(scene), "tavern")
        for scene in ("bree", "north_gate", "north-gate", "road-fork", "watch-post", "road_from_bree", "marsh", "camp"):
            self.assertEqual(soundscape_for_scene(scene), "outdoors")
        for scene in ("wayhouse", "hall", "bridge", "drowned-mile", "sluice", "part2_descent", "part2_last_seal", "seal"):
            self.assertEqual(soundscape_for_scene(scene), "buried")
        for scene in ("lantern", "refuge", "part2_house_under_ash", "part2_vigil", "complete"):
            self.assertEqual(soundscape_for_scene(scene), "lantern")
        for scene in (None, "", "menu", "MAIN MENU", "title", "pause"):
            self.assertIsNone(soundscape_for_scene(scene))
        self.assertEqual(soundscape_for_scene("pony", combat=True), "combat")

    def test_surface_steps_have_distinct_quiet_textures_and_alternating_feet(self):
        textures = []
        for surface in ("wood", "stone", "mud", "grass"):
            first = _effect_wave("footstep", surface=surface, variant=0)
            second = _effect_wave("footstep", surface=surface, variant=1)
            self.assertNotEqual(first, second)
            self.assertEqual(first, _effect_wave("footstep", surface=surface, variant=0))
            for data in (first, second):
                with wave.open(io.BytesIO(data), "rb") as source:
                    samples = array("h", source.readframes(source.getnframes()))
                    self.assertLess(max(map(abs, samples)), 2_000)
            textures.append(first)
        self.assertEqual(len(set(textures)), 4)


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
        self.player.update(1.0, enabled=True, music_volume=0.0, sfx_volume=0.0)
        self.assertIsNone(self.pg.mixer.get_init())

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

    def test_a_long_reading_and_exploration_sequence_keeps_the_same_score_running(self):
        self.player.set_scene("pony")
        self.player.update(FADE_SECONDS)
        class ChannelMonitor:
            def __init__(self, channel):
                self.channel = channel
                self.restarts = 0
            def __getattr__(self, name):
                return getattr(self.channel, name)
            def play(self, *args, **kwargs):
                self.restarts += 1
                return self.channel.play(*args, **kwargs)
        monitors = []
        for voice in self.player._voices:
            voice.channel = ChannelMonitor(voice.channel)
            monitors.append(voice.channel)
        # Fifteen simulated minutes of reading, examining props, and returning
        # to the same room must not re-cue the opening notes on every request.
        for _ in range(15):
            for scene in ("pony", "chapter1_decision", "branch_search", "broken_key", "aftermath", "tavern-interior"):
                self.player.set_scene(scene)
                self.player.update(10.0)
        self.assertEqual(sum(monitor.restarts for monitor in monitors), 0)
        self.assertEqual(len(self.player._sounds), 1)
        self.assertTrue(any(voice.channel.get_busy() for voice in self.player._voices))

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

    def test_battle_effects_use_one_cached_channel_without_restarting_the_score(self):
        self.player.set_scene("hall", combat=True)
        self.player.update(FADE_SECONDS, sfx_volume=0.37)
        music = next(voice for voice in self.player._voices if voice.track)
        score = music.channel.get_sound()
        for effect in BATTLE_EFFECTS:
            self.player._effect_channel.stop()
            self.player.update(0.3, sfx_volume=0.37)
            self.assertTrue(self.player.play_effect(effect))
            cached = self.player._effects[effect]
            self.assertFalse(self.player.play_effect(effect))
            self.assertIs(music.channel.get_sound(), score)
            self.assertAlmostEqual(self.player._effect_channel.get_volume(), 0.37, delta=0.01)
            self.player._effect_channel.stop()
            self.player.update(0.3, sfx_volume=0.37)
            self.assertTrue(self.player.play_effect(effect))
            self.assertIs(self.player._effects[effect], cached)
        self.assertEqual(len(self.player._effects), len(BATTLE_EFFECTS))
        self.assertEqual(len(self.player._voices), 2)

    def test_hover_cannot_cut_off_a_battle_fall_and_higher_priority_fall_can_replace_a_hit(self):
        self.player.set_scene("hall", combat=True)
        self.player.update(FADE_SECONDS)
        self.assertTrue(self.player.play_effect("hit"))
        self.assertFalse(self.player.play_effect("block"))
        self.assertTrue(self.player.play_effect("fall"))
        sound = self.player._effect_channel.get_sound()
        self.assertFalse(self.player.play_effect("hover"))
        self.assertFalse(self.player.play_effect("footstep"))
        self.assertFalse(self.player.play_effect("interact"))
        self.assertIs(self.player._effect_channel.get_sound(), sound)

    def test_battle_reactions_obey_mute_and_recover_after_a_device_reopens(self):
        self.player.set_scene("hall", combat=True)
        self.player.update(0.1, enabled=False)
        for effect in BATTLE_EFFECTS:
            self.assertFalse(self.player.play_effect(effect))
        self.assertIsNone(self.pg.mixer.get_init())
        self.player.update(FADE_SECONDS, enabled=True)
        self.assertTrue(self.player.play_effect("guard"))
        old = self.player._effects["guard"]
        self.pg.mixer.quit()
        self.player.update(FADE_SECONDS)
        self.assertTrue(self.player.play_effect("guard"))
        self.assertIsNot(self.player._effects["guard"], old)
        self.player.update(0.01, enabled=False)
        self.assertFalse(self.player._effect_channel.get_busy())
        self.player.update(FADE_SECONDS, enabled=True, sfx_volume=0)
        for effect in BATTLE_EFFECTS:
            self.assertFalse(self.player.play_effect(effect))

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
        cue_channel = self.pg.mixer.Channel(5)
        cue_channel.play(cue, loops=-1)
        self.player.stop()
        self.assertTrue(cue_channel.get_busy())
        self.assertIsNotNone(self.pg.mixer.get_init())

    def test_story_cues_obey_current_preferences_even_before_an_ambience_frame(self):
        self.assertFalse(self.player.play_cue("notice", enabled=False, volume=0.6))
        self.assertFalse(self.player.play_cue("notice", enabled=True, volume=0.0))
        self.assertIsNone(self.pg.mixer.get_init())
        self.assertTrue(self.player.play_cue("notice", enabled=True, volume=0.43))
        cue = next(voice for voice in self.player._cue_voices if voice.channel.get_busy())
        self.assertAlmostEqual(cue.channel.get_volume(), 0.43, delta=0.01)
        self.assertFalse(self.player.play_cue("danger", enabled=False, volume=1.0))
        self.player.update(0.01, enabled=False)
        self.assertFalse(any(voice.channel.get_busy() for voice in self.player._cue_voices))

    def test_important_story_cues_have_priority_and_repeated_cues_are_rate_limited(self):
        self.player.set_scene("pony")
        self.player.update(FADE_SECONDS)
        self.assertTrue(self.player.play_cue("notice"))
        self.assertTrue(self.player.play_cue("victory"))
        self.assertFalse(self.player.play_cue("notice"))
        self.assertTrue(self.player.play_cue("danger"))
        self.assertEqual({voice.cue for voice in self.player._cue_voices}, {"victory", "danger"})
        self.assertFalse(self.player.play_cue("discovery"))

    def test_story_cues_gently_duck_music_and_music_recovers_afterward(self):
        self.player.set_scene("bree")
        self.player.update(FADE_SECONDS)
        music = next(voice for voice in self.player._voices if voice.track)
        initial = music.channel.get_volume()
        self.assertTrue(self.player.play_cue("discovery"))
        self.player.update(0.08)
        reduced = music.channel.get_volume()
        self.assertLess(reduced, initial)
        self.assertGreater(reduced, initial * 0.55)
        for cue in self.player._cue_voices:
            cue.channel.stop()
        self.player.update(2.0)
        self.assertGreater(music.channel.get_volume(), reduced)
        self.assertAlmostEqual(music.channel.get_volume(), initial, delta=0.01)

    def test_a_closed_device_is_reopened_with_fresh_buffers_and_the_same_scene(self):
        self.player.set_scene("hall")
        self.player.update(FADE_SECONDS)
        previous = self.player._sounds["buried"]
        self.pg.mixer.quit()
        self.player.update(FADE_SECONDS)
        self.assertIsNotNone(self.pg.mixer.get_init())
        self.assertIsNot(self.player._sounds["buried"], previous)
        self.assertTrue(any(voice.channel.get_busy() for voice in self.player._voices))
        self.assertEqual(self.player.scene, "buried")

    def test_unavailable_device_retries_at_a_bounded_rate_and_recovers(self):
        self.player.set_scene("pony")
        with mock.patch.object(self.pg.mixer, "init", side_effect=self.pg.error("No device")) as initialise:
            self.player.update(0.1)
            self.player.update(0.1)
            self.player.update(0.1)
            self.assertEqual(initialise.call_count, 1)
        self.player.update(RETRY_SECONDS + 0.1)
        self.assertTrue(self.player.available)
        self.assertTrue(any(voice.channel.get_busy() for voice in self.player._voices))

    def test_pathological_runtime_volumes_and_elapsed_time_are_silent_safe_values(self):
        self.player.set_scene("pony")
        self.player.update(10 ** 1000, music_volume=10 ** 1000, sfx_volume=True)
        self.assertEqual(self.player._clock, 0.0)
        self.assertFalse(self.player.play_effect("hover"))
        self.assertFalse(self.player.play_cue("notice", enabled=True, volume=10 ** 1000))


if __name__ == "__main__":
    unittest.main()
