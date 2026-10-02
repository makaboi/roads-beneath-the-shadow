from array import array
import math
import unittest
from unittest import mock

import wave

from roads_beneath_shadow.audio import AUDIO_DIRECTORY, SoundPlayer


class SoundPlayerTests(unittest.TestCase):
    def test_every_original_cue_is_packaged(self) -> None:
        self.assertEqual(SoundPlayer.missing_cues(), [])

    def test_original_cues_have_consistent_levels_and_click_free_edges(self) -> None:
        for filename in SoundPlayer.CUES.values():
            with self.subTest(cue=filename), wave.open(str(AUDIO_DIRECTORY / filename), "rb") as source:
                samples = array("h", source.readframes(source.getnframes()))
                self.assertEqual((samples[0], samples[-1]), (0, 0))
                rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
                self.assertAlmostEqual(20 * math.log10(rms), -24.0, delta=0.1)
                self.assertLess(max(map(abs, samples)), 10_000)

    def test_missing_platform_player_is_a_safe_noop(self) -> None:
        player = SoundPlayer()
        player._player = None
        self.assertFalse(player.play("danger"))

    def test_known_cue_uses_nonblocking_platform_player(self) -> None:
        player = SoundPlayer()
        player._player = "/usr/bin/afplay"
        with mock.patch("roads_beneath_shadow.audio.subprocess.Popen") as popen:
            self.assertTrue(player.play("victory"))
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/afplay")
        self.assertTrue(command[1].endswith("victory.wav"))


if __name__ == "__main__":
    unittest.main()
