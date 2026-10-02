"""Generate the game's original, deterministic retro sound cues."""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "roads_beneath_shadow" / "audio_assets"
SAMPLE_RATE = 22_050


def oscillator(frequency: float, moment: float, kind: str = "triangle") -> float:
    phase = (moment * frequency) % 1.0
    if kind == "sine":
        return math.sin(phase * math.tau)
    if kind == "square":
        return 1.0 if phase < 0.5 else -1.0
    return 4.0 * abs(phase - 0.5) - 1.0


def cue(notes: list[tuple[float, float, float, str]], duration: float, *, noise: float = 0.0) -> list[int]:
    rng = random.Random(1937)
    samples: list[int] = []
    for index in range(round(duration * SAMPLE_RATE)):
        moment = index / SAMPLE_RATE
        mixed = 0.0
        for start, length, frequency, kind in notes:
            local = moment - start
            if not 0 <= local < length:
                continue
            attack = min(1.0, local / 0.018)
            release = min(1.0, (length - local) / 0.10)
            envelope = attack * release
            mixed += oscillator(frequency, local, kind) * envelope
            mixed += oscillator(frequency * 2.01, local, "sine") * envelope * 0.16
        if noise:
            mixed += rng.uniform(-noise, noise) * min(1.0, moment / 0.012) * max(0.0, 1.0 - moment / duration)
        samples.append(max(-32767, min(32767, round(mixed * 7200))))
    # Keep every cue at a consistent, comfortable level so discoveries do not
    # shout over quiet exploration. Short edge fades also soften noise tails.
    edge = max(1, round(0.008 * SAMPLE_RATE))
    for index in range(min(edge, len(samples))):
        gain = index / edge
        samples[index] = round(samples[index] * gain)
        samples[-1 - index] = round(samples[-1 - index] * gain)
    rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
    peak = max((abs(value) for value in samples), default=1)
    gain = min(32767 * 10 ** (-24 / 20) / max(1, rms), 32767 * 0.30 / max(1, peak))
    return [round(value * gain) for value in samples]


def write(name: str, samples: list[int]) -> None:
    path = OUTPUT / name
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write("notice.wav", cue([(0.00, 0.18, 440, "triangle"), (0.14, 0.26, 660, "triangle")], 0.46))
    write(
        "danger.wav",
        cue([(0.00, 0.55, 82.4, "square"), (0.10, 0.45, 87.3, "triangle")], 0.62, noise=0.07),
    )
    write(
        "victory.wav",
        cue(
            [
                (0.00, 0.28, 220.0, "triangle"),
                (0.18, 0.30, 277.2, "triangle"),
                (0.36, 0.50, 329.6, "triangle"),
                (0.50, 0.38, 440.0, "sine"),
            ],
            0.92,
        ),
    )
    write(
        "discovery.wav",
        cue(
            [
                (0.00, 0.35, 523.3, "sine"),
                (0.13, 0.42, 659.3, "sine"),
                (0.28, 0.55, 784.0, "sine"),
            ],
            0.88,
        ),
    )
    write(
        "corruption.wav",
        cue(
            [
                (0.00, 0.40, 196.0, "triangle"),
                (0.20, 0.48, 146.8, "square"),
                (0.42, 0.50, 98.0, "triangle"),
            ],
            0.96,
            noise=0.04,
        ),
    )


if __name__ == "__main__":
    main()
