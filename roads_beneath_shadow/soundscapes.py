"""Optional original ambience for the graphical adventure.

The player owns two reserved mixer channels, so changing rooms can crossfade
without interrupting a cue or blocking the render loop. Importing this module
and constructing the player never opens an audio device. The first enabled
``update`` does that, and a missing device or asset is a silent fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
from pathlib import Path
import random
import struct
from typing import Any
import wave


AUDIO_DIRECTORY = Path(__file__).with_name("audio_assets")
TRACKS = {
    "tavern": "ambient-tavern.wav",
    "outdoors": "ambient-outdoors.wav",
    "buried": "ambient-buried.wav",
    "lantern": "ambient-lantern.wav",
    "combat": "ambient-combat.wav",
}
FADE_SECONDS = 1.1


def soundscape_for_scene(scene: str | None, *, combat: bool = False) -> str | None:
    """Resolve world-map keys, story-state IDs, and illustration scene keys."""

    if combat:
        return "combat"
    if scene is None:
        return None
    key = str(scene).casefold().strip().replace("-", "_").replace(" ", "_")
    if key in {"", "menu", "main_menu", "title", "settings", "credits", "pause"}:
        return None
    if key in TRACKS:
        return key
    if key in {"pony", "tavern_interior", "aftermath", "broken_key", "sword"}:
        return "tavern"
    if key.startswith(("chapter1_", "branch_")):
        return "tavern"
    if key in {"lantern", "last_lantern", "part2_vigil", "complete"}:
        return "lantern"
    if key in {"wayhouse", "hall", "seal", "cages", "key", "map"}:
        return "buried"
    if key.startswith("part2_"):
        return "buried"
    if key in {"rider", "orc", "warg", "ghorak", "troll"}:
        return "buried"
    return "outdoors"


def _volume(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


@dataclass
class _Voice:
    channel: Any
    track: str | None = None
    gain: float = 0.0
    target: float = 0.0


class SoundscapePlayer:
    """Drive this from the SDL thread using elapsed seconds on each frame.

    ``set_scene(None)`` gently suspends the score, for example on the main
    menu. Turning sound off is immediate. Mixer channels 0–2 are reserved;
    channel 2 plays the quiet, rate-limited interaction sounds, and automatic
    pygame channel allocation remains available from channel 3 onward.
    """

    def __init__(self, pg: Any, asset_dir: Path | str | None = None) -> None:
        self.pg = pg
        self.asset_dir = Path(asset_dir) if asset_dir is not None else AUDIO_DIRECTORY
        self._desired: str | None = None
        self._voices: list[_Voice] = []
        self._effect_channel: Any = None
        self._sounds: dict[str, Any] = {}
        self._effects: dict[str, Any] = {}
        self._missing: set[str] = set()
        self._failed = False
        self._enabled = False
        self._sfx_volume = 0.6
        self._clock = 0.0
        self._last_effect: dict[str, float] = {}

    @property
    def available(self) -> bool:
        return not self._failed and any(
            (self.asset_dir / filename).is_file() for filename in TRACKS.values()
        )

    @property
    def scene(self) -> str | None:
        """The selected soundscape, including while playback is muted."""

        return self._desired

    def set_scene(self, scene: str | None, combat: bool = False) -> None:
        self._desired = soundscape_for_scene(scene, combat=combat)

    def _ensure_mixer(self) -> bool:
        if self._failed:
            return False
        if self._voices:
            return True
        try:
            if self.pg.mixer.get_init() is None:
                self.pg.mixer.init(frequency=16_000, size=-16, channels=2, buffer=512)
            if self.pg.mixer.get_num_channels() < 8:
                self.pg.mixer.set_num_channels(8)
            self.pg.mixer.set_reserved(3)
            self._voices = [_Voice(self.pg.mixer.Channel(index)) for index in range(2)]
            self._effect_channel = self.pg.mixer.Channel(2)
        except (AttributeError, RuntimeError, OSError, self.pg.error):
            self._failed = True
            self._voices.clear()
            return False
        return True

    def _sound_for(self, track: str) -> Any:
        if track in self._missing:
            return None
        if track not in self._sounds:
            path = self.asset_dir / TRACKS[track]
            try:
                self._sounds[track] = self.pg.mixer.Sound(str(path))
            except (OSError, RuntimeError, self.pg.error):
                self._missing.add(track)
                return None
        return self._sounds[track]

    def _select_voice(self) -> None:
        for voice in self._voices:
            voice.target = 0.0
        if self._desired is None:
            return
        for voice in self._voices:
            if voice.track == self._desired:
                voice.target = 1.0
                return
        sound = self._sound_for(self._desired)
        if sound is None:
            return
        # Usually this is an idle channel. If a player changes rooms faster
        # than the fade, reuse the quieter channel and retain the louder bed.
        voice = min(self._voices, key=lambda candidate: candidate.gain)
        voice.channel.stop()
        voice.channel.set_volume(0.0)
        voice.channel.play(sound, loops=-1)
        voice.track = self._desired
        voice.gain = 0.0
        voice.target = 1.0

    def update(
        self,
        dt: float,
        enabled: bool = True,
        music_volume: float = 0.25,
        sfx_volume: float = 0.6,
    ) -> None:
        """Advance nonblocking crossfades; disabled audio never starts a mixer."""

        try:
            elapsed = float(dt)
        except (TypeError, ValueError):
            elapsed = 0.0
        elapsed = max(0.0, elapsed) if math.isfinite(elapsed) else 0.0
        self._clock += elapsed
        self._enabled = bool(enabled)
        self._sfx_volume = _volume(sfx_volume)
        if not self._enabled:
            self._silence()
            return
        if not self._voices and (self._desired is None or not self.available):
            return
        if not self._ensure_mixer():
            return
        try:
            self._select_voice()
            step = elapsed / FADE_SECONDS
            volume = _volume(music_volume)
            for voice in self._voices:
                if voice.gain < voice.target:
                    voice.gain = min(voice.target, voice.gain + step)
                else:
                    voice.gain = max(voice.target, voice.gain - step)
                # Equal-power fades keep the bed from dipping at the midpoint.
                voice.channel.set_volume(math.sin(voice.gain * math.pi / 2) * volume)
                if voice.target == 0.0 and voice.gain == 0.0 and voice.track is not None:
                    voice.channel.stop()
                    voice.track = None
            self._effect_channel.set_volume(self._sfx_volume)
        except (RuntimeError, self.pg.error):
            # SDL can lose an audio device during play; presentation still runs.
            self._failed = True
            self._silence()

    def play_effect(self, effect: str) -> bool:
        """Play a quiet footstep, interaction, or hover with a per-effect cooldown."""

        cooldowns = {"footstep": 0.23, "interact": 0.2, "hover": 0.16}
        if (
            effect not in cooldowns
            or not self._enabled
            or self._sfx_volume == 0.0
            or self._desired is None
            or self._clock - self._last_effect.get(effect, -math.inf) < cooldowns[effect]
            or not self._ensure_mixer()
        ):
            return False
        try:
            if effect not in self._effects:
                self._effects[effect] = self.pg.mixer.Sound(file=io.BytesIO(_effect_wave(effect)))
            if effect == "footstep" and self._effect_channel.get_busy():
                return False
            self._effect_channel.set_volume(self._sfx_volume)
            self._effect_channel.play(self._effects[effect])
            self._last_effect[effect] = self._clock
        except (OSError, RuntimeError, self.pg.error):
            return False
        return True

    def _silence(self) -> None:
        for voice in self._voices:
            try:
                voice.channel.stop()
            except (RuntimeError, self.pg.error):
                pass
            voice.track = None
            voice.gain = voice.target = 0.0
        if self._effect_channel is not None:
            try:
                self._effect_channel.stop()
            except (RuntimeError, self.pg.error):
                pass

    def stop(self) -> None:
        """Stop owned channels without stopping unrelated cues or quitting SDL."""

        self._desired = None
        self._enabled = False
        self._silence()


def _effect_wave(effect: str) -> bytes:
    """Small deterministic, original sounds; generated once and cached by SDL."""

    sample_rate = 16_000
    duration = {"footstep": 0.085, "interact": 0.16, "hover": 0.055}[effect]
    rng = random.Random(1789)
    data = bytearray()
    low_noise = 0.0
    for index in range(round(duration * sample_rate)):
        t = index / sample_rate
        envelope = min(1.0, t / 0.005) * (1.0 - t / duration) ** 2
        if effect == "footstep":
            low_noise += (rng.uniform(-1.0, 1.0) - low_noise) * 0.19
            value = (low_noise * 0.62 + math.sin(math.tau * 92 * t) * 0.28) * envelope
            amplitude = 2_100
        elif effect == "interact":
            value = (math.sin(math.tau * 523.25 * t) + 0.35 * math.sin(math.tau * 784 * t)) * envelope
            amplitude = 2_100
        else:
            value = math.sin(math.tau * 660 * t) * envelope
            amplitude = 850
        sample = round(value * amplitude)
        data.extend(struct.pack("<hh", sample, sample))
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(data)
    return stream.getvalue()
