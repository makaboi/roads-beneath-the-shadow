"""Synthesize the adventure's original seamless ambient loops, without samples.

All oscillators, instrument envelopes, weather beds, and rhythms are authored
here. Seeds are fixed, tones complete an integer number of cycles, and notes
wrap around the loop. Re-running this script reproduces the packaged WAVs.
Only Python's standard library is used.
"""

from __future__ import annotations

from array import array
import math
from pathlib import Path
import random
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "roads_beneath_shadow" / "audio_assets"
SAMPLE_RATE = 16_000
DURATION = 20.0
SCENES = ("tavern", "outdoors", "buried", "lantern", "combat")


class Canvas:
    def __init__(self, sample_rate: int, duration: float) -> None:
        self.rate = sample_rate
        self.duration = duration
        self.frames = round(sample_rate * duration)
        self.left = array("d", [0.0]) * self.frames
        self.right = array("d", [0.0]) * self.frames

    def tone(
        self, frequency: float, gain: float, *, pan: float = 0.0,
        phase: float = 0.0, swell: float = 0.0, cycles: int = 1,
    ) -> None:
        """A periodic sine pad with a slow, also-periodic dynamic envelope."""

        frequency = round(frequency * self.duration) / self.duration
        increment = math.tau * frequency / self.rate
        sin_step, cos_step = math.sin(increment), math.cos(increment)
        sine, cosine = math.sin(phase), math.cos(phase)
        left, right = math.sqrt((1.0 - pan) / 2), math.sqrt((1.0 + pan) / 2)
        for index in range(self.frames):
            envelope = 1.0 - swell + swell * (0.5 + 0.5 * math.sin(math.tau * cycles * index / self.frames + phase))
            value = sine * gain * envelope
            self.left[index] += value * left
            self.right[index] += value * right
            sine, cosine = sine * cos_step + cosine * sin_step, cosine * cos_step - sine * sin_step

    def note(
        self, start: float, length: float, frequency: float, gain: float,
        *, instrument: str = "flute", pan: float = 0.0,
    ) -> None:
        """Wrap an instrument's natural decay across the end of the loop."""

        left, right = math.sqrt((1.0 - pan) / 2), math.sqrt((1.0 + pan) / 2)
        harmonics = {
            "flute": ((1, 1.0), (2, 0.16), (3, 0.035)),
            "pluck": ((1, 1.0), (2, 0.34), (3, 0.14), (4, 0.065)),
            "bell": ((1, 0.7), (2.01, 0.38), (2.76, 0.17), (4.07, 0.075)),
            "drum": ((1, 0.85), (1.51, 0.28), (2.13, 0.1)),
        }[instrument]
        frames = round(length * self.rate)
        beginning = round(start * self.rate)
        for index in range(frames):
            t = index / self.rate
            attack = min(1.0, t / (0.15 if instrument == "flute" else 0.006))
            release = min(1.0, (length - t) / 0.2)
            envelope = attack * release
            if instrument != "flute":
                envelope *= math.exp(-t * (5.5 if instrument == "drum" else 1.8))
            else:
                envelope *= 0.8 + 0.2 * math.sin(math.pi * t / length)
            vibrato = 0.012 * math.sin(math.tau * 4.7 * t) if instrument == "flute" else 0.0
            phase = math.tau * frequency * t + vibrato
            value = sum(math.sin(phase * ratio) * weight for ratio, weight in harmonics) * envelope * gain
            position = (beginning + index) % self.frames
            self.left[position] += value * left
            self.right[position] += value * right

    def weather(self, seed: int, gain: float, *, wind: bool = False) -> None:
        rng = random.Random(seed)
        noise = array("d", (rng.uniform(-1.0, 1.0) for _ in range(self.frames)))
        coefficient = 0.012 if wind else 0.24
        low = side = 0.0
        # Warm the filters on the same circular material before storing audio.
        for value in noise:
            low += (value - low) * coefficient
            side += (value - side) * coefficient * 0.43
        for index, value in enumerate(noise):
            low += (value - low) * coefficient
            side += (value - side) * coefficient * 0.43
            swell = 0.62 + 0.22 * math.sin(math.tau * index / self.frames) + 0.16 * math.sin(math.tau * 3 * index / self.frames + 1.1)
            self.left[index] += (low * 0.75 + side * 0.25) * gain * swell
            self.right[index] += (low * 0.56 + side * 0.44) * gain * swell

    def samples(self) -> array:
        peak = max(max(abs(value) for value in self.left), max(abs(value) for value in self.right), 0.001)
        rms = math.sqrt((sum(value * value for value in self.left) + sum(value * value for value in self.right)) / (self.frames * 2))
        # Match perceived bed levels across rooms rather than making quiet
        # wind nearly disappear at the default volume. A -23 dBFS RMS target
        # remains restrained, and the peak ceiling leaves ample cue headroom.
        scale = min(10 ** (-23 / 20) / max(rms, 0.001), 0.29 / peak)
        result = array("h")
        for left, right in zip(self.left, self.right):
            result.append(round(left * scale * 32_767))
            result.append(round(right * scale * 32_767))
        # Matching endpoints removes a click even on a mixer that duplicates
        # its final sample. Changes here are smaller than an ordinary sample.
        for channel in (0, 1):
            value = round((result[channel] + result[-2 + channel]) / 2)
            result[channel] = result[-2 + channel] = value
        return result


def generate_track(scene: str, *, sample_rate: int = SAMPLE_RATE, duration: float = DURATION) -> array:
    """Return interleaved signed-16-bit stereo samples, with deterministic seeds."""

    if scene not in SCENES:
        raise ValueError(f"Unknown soundscape: {scene}")
    canvas = Canvas(sample_rate, duration)
    stretch = duration / DURATION

    def note(start: float, length: float, frequency: float, gain: float, **kwargs: object) -> None:
        canvas.note(start * stretch, length * stretch, frequency, gain, **kwargs)

    if scene == "tavern":
        # A quiet D-minor hearth: rain under a few breathy woodwind phrases.
        canvas.weather(1_937, 0.095)
        for frequency, gain, pan in ((73.416, 0.033, -0.18), (146.832, 0.021, 0.22), (220, 0.016, 0.0)):
            canvas.tone(frequency, gain, pan=pan, swell=0.6)
        for start, frequency in ((0.9, 293.665), (4.2, 349.228), (7.1, 440), (11.4, 392), (15.2, 349.228), (18.4, 293.665)):
            note(start, 1.75, frequency, 0.033, pan=-0.23)
        for start, frequency in ((2.2, 146.832), (8.8, 220), (13.0, 174.614), (17.0, 220)):
            note(start, 1.2, frequency, 0.022, instrument="pluck", pan=0.36)
    elif scene == "outdoors":
        # Wind from the north road, with sparse bells beyond Bree's walls.
        canvas.weather(4_101, 0.23, wind=True)
        for frequency, gain, pan in ((98, 0.020, -0.5), (146.832, 0.016, 0.44), (196, 0.008, 0.0)):
            canvas.tone(frequency, gain, pan=pan, swell=0.85, cycles=2)
        for start, frequency, pan in ((1.0, 587.33, -0.55), (7.8, 440, 0.52), (14.5, 659.255, -0.3)):
            note(start, 4.5, frequency, 0.019, instrument="bell", pan=pan)
        note(18.7, 3.0, 293.665, 0.012, instrument="flute", pan=0.25)
    elif scene == "buried":
        # Stone resonance below the wayhouse: overlapping, slowly moving modes.
        for frequency, gain, pan, phase in ((55, 0.040, -0.12, 0.0), (82.4, 0.023, 0.35, 1.0), (110.15, 0.018, -0.4, 0.3), (164.8, 0.012, 0.5, 2.0), (220.3, 0.010, 0.0, 0.7)):
            canvas.tone(frequency, gain, pan=pan, phase=phase, swell=0.8, cycles=2)
        canvas.weather(8_019, 0.065, wind=True)
        for start, frequency, pan in ((2.1, 329.628, -0.6), (9.2, 246.942, 0.55), (15.6, 311.127, -0.15)):
            note(start, 4.7, frequency, 0.017, instrument="bell", pan=pan)
    elif scene == "lantern":
        # A restrained plucked-string theme for companionship at the last light.
        for frequency, gain, pan in ((73.416, 0.024, -0.15), (146.832, 0.015, 0.25), (220, 0.011, 0.0)):
            canvas.tone(frequency, gain, pan=pan, swell=0.8)
        canvas.weather(7_151, 0.035, wind=True)
        melody = (293.665, 440, 349.228, 293.665, 261.626, 349.228, 392, 440, 349.228, 293.665)
        for index, frequency in enumerate(melody):
            note(index * 2.0 + 0.25, 2.7, frequency, 0.055, instrument="pluck", pan=(-0.32 if index % 2 else 0.32))
        for start, frequency in ((1.0, 146.832), (6.9, 174.614), (12.9, 130.813), (18.9, 146.832)):
            note(start, 3.3, frequency, 0.030, instrument="pluck", pan=-0.12)
    else:
        # Low drums and a dark pulse add pressure without masking story text.
        for frequency, gain, pan in ((55, 0.039, -0.2), (82.4, 0.023, 0.2), (116.55, 0.013, 0.0)):
            canvas.tone(frequency, gain, pan=pan, swell=0.6, cycles=5)
        canvas.weather(9_702, 0.055, wind=True)
        for index in range(10):
            note(index * 2.0, 0.78, 49, 0.115 if index % 2 == 0 else 0.075, instrument="drum", pan=-0.2)
            note(index * 2.0 + 1.25, 0.44, 73.416, 0.048, instrument="drum", pan=0.28)
        for start, frequency in ((0.45, 146.832), (5.45, 155.563), (10.45, 146.832), (15.45, 130.813)):
            note(start, 3.7, frequency, 0.029, instrument="flute", pan=0.1)
    return canvas.samples()


def write_track(scene: str, output: Path = OUTPUT) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    samples = generate_track(scene)
    if sys.byteorder != "little":
        samples.byteswap()
    path = output / f"ambient-{scene}.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(samples.tobytes())
    return path


def main() -> None:
    for scene in SCENES:
        path = write_track(scene)
        print(f"{path.name}: {DURATION:g}s, stereo {SAMPLE_RATE}Hz, {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
