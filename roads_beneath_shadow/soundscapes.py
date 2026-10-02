"""Optional original ambience for the graphical adventure.

The player owns two music channels and three cue channels, so changing rooms
can crossfade without interrupting a cue or blocking the render loop. Importing this module
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

from .audio import SoundPlayer

AUDIO_DIRECTORY = Path(__file__).with_name("audio_assets")
TRACKS = {
    "tavern": "ambient-tavern.wav",
    "outdoors": "ambient-outdoors.wav",
    "buried": "ambient-buried.wav",
    "lantern": "ambient-lantern.wav",
    "combat": "ambient-combat.wav",
}
FADE_SECONDS = 1.1
RETRY_SECONDS = 3.0
CUE_PRIORITY = {"notice": 0, "discovery": 1, "victory": 2, "corruption": 2, "danger": 3}
BATTLE_EFFECTS = {
    "hit": 0.105, "block": 0.16, "hurt": 0.14, "heal": 0.26,
    "guard": 0.18, "evade": 0.13, "interrupt": 0.12, "fall": 0.28,
    "escape": 0.22,
}
EFFECT_COOLDOWNS = {
    "footstep": 0.23, "interact": 0.2, "hover": 0.16,
    "hit": 0.08, "block": 0.12, "hurt": 0.18, "heal": 0.18,
    "guard": 0.18, "evade": 0.12, "interrupt": 0.15, "fall": 0.2,
    "escape": 0.25,
}
EFFECT_PRIORITY = {
    "footstep": 0, "hover": 0, "interact": 1,
    "hit": 2, "block": 2, "hurt": 2, "guard": 2, "evade": 2,
    "heal": 3, "interrupt": 3, "fall": 4, "escape": 4,
}


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
    if key in {"lantern", "refuge", "last_lantern", "part2_vigil", "part2_house_under_ash", "part2_burning_memory", "complete"}:
        return "lantern"
    if key in {"wayhouse", "hall", "bridge", "drowned_mile", "sluice", "seal", "cages", "key", "map"}:
        return "buried"
    if key.startswith("part2_"):
        return "buried"
    if key in {"rider", "orc", "warg", "ghorak", "troll"}:
        return "buried"
    return "outdoors"


def _volume(value: float) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


@dataclass
class _Voice:
    channel: Any
    track: str | None = None
    gain: float = 0.0
    target: float = 0.0


@dataclass
class _CueVoice:
    channel: Any
    cue: str | None = None
    priority: int = -1


class SoundscapePlayer:
    """Drive this from the SDL thread using elapsed seconds on each frame.

    ``set_scene(None)`` gently suspends the score, for example on the main
    menu. Turning sound off is immediate. Mixer channels 0–4 are reserved;
    channel 2 plays quiet interactions and 3–4 play story cues. Automatic
    pygame channel allocation remains available from channel 5 onward.
    """

    def __init__(self, pg: Any, asset_dir: Path | str | None = None) -> None:
        self.pg = pg
        self.asset_dir = Path(asset_dir) if asset_dir is not None else AUDIO_DIRECTORY
        self._desired: str | None = None
        self._voices: list[_Voice] = []
        self._effect_channel: Any = None
        self._effect_playing: str | None = None
        self._cue_voices: list[_CueVoice] = []
        self._cue_sounds: dict[str, Any] = {}
        self._sounds: dict[str, Any] = {}
        self._effects: dict[str, Any] = {}
        self._missing: set[str] = set()
        self._failed = False
        self._retry_at = 0.0
        self._mixer_format: tuple[int, int, int] | None = None
        self._duck = 1.0
        self._music_level: float | None = None
        self._enabled = False
        self._sfx_volume = 0.6
        self._clock = 0.0
        self._last_effect: dict[str, float] = {}
        self._last_cue: dict[str, float] = {}
        self._footstep_number = 0

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
        if self._failed and self._clock < self._retry_at:
            return False
        try:
            current = self.pg.mixer.get_init()
            if self._voices and not self._failed and current is not None and current == self._mixer_format:
                return True
            # SDL objects and decoded buffers belong to a mixer generation.
            # Drop them after a device closes or its format changes, then let
            # the next enabled frame reopen the selected room's score.
            self._voices.clear()
            self._cue_voices.clear()
            self._effect_channel = None
            self._effect_playing = None
            self._sounds.clear()
            self._cue_sounds.clear()
            self._effects.clear()
            if current is None:
                self.pg.mixer.init(frequency=16_000, size=-16, channels=2, buffer=512)
            if self.pg.mixer.get_num_channels() < 8:
                self.pg.mixer.set_num_channels(8)
            self.pg.mixer.set_reserved(5)
            self._voices = [_Voice(self.pg.mixer.Channel(index)) for index in range(2)]
            self._effect_channel = self.pg.mixer.Channel(2)
            self._cue_voices = [_CueVoice(self.pg.mixer.Channel(index)) for index in (3, 4)]
            self._mixer_format = self.pg.mixer.get_init()
            self._failed = False
        except (AttributeError, RuntimeError, OSError, self.pg.error):
            self._failed = True
            self._retry_at = self._clock + RETRY_SECONDS
            self._voices.clear()
            self._cue_voices.clear()
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
                if not voice.channel.get_busy():
                    sound = self._sound_for(self._desired)
                    if sound is None:
                        return
                    voice.channel.set_volume(0.0)
                    voice.channel.play(sound, loops=-1)
                    voice.gain = 0.0
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
        except (TypeError, ValueError, OverflowError):
            elapsed = 0.0
        elapsed = max(0.0, elapsed) if math.isfinite(elapsed) else 0.0
        self._clock += elapsed
        self._enabled = bool(enabled)
        self._sfx_volume = _volume(sfx_volume)
        music_level = _volume(music_volume)
        if not self._enabled:
            self._silence()
            return
        if music_level == 0.0 and self._sfx_volume == 0.0:
            self._silence()
            return
        if not self._voices and self._desired is None:
            return
        if not self._voices and not self._failed and not self.available:
            return
        if not self._ensure_mixer():
            return
        try:
            self._select_voice()
            step = elapsed / FADE_SECONDS
            if self._music_level is None or music_level == 0.0:
                self._music_level = music_level
            else:
                self._music_level += (music_level - self._music_level) * (1.0 - math.exp(-elapsed / 0.08))
            volume = self._music_level
            cue_busy = any(voice.channel.get_busy() for voice in self._cue_voices)
            duck_target = 0.60 if cue_busy else 1.0
            duck_seconds = 0.08 if cue_busy else 0.65
            blend = 1.0 - math.exp(-elapsed / duck_seconds)
            self._duck += (duck_target - self._duck) * blend
            for voice in self._voices:
                if voice.gain < voice.target:
                    voice.gain = min(voice.target, voice.gain + step)
                else:
                    voice.gain = max(voice.target, voice.gain - step)
                # Equal-power fades keep the bed from dipping at the midpoint.
                voice.channel.set_volume(math.sin(voice.gain * math.pi / 2) * volume * self._duck)
                if voice.target == 0.0 and voice.gain == 0.0 and voice.track is not None:
                    voice.channel.stop()
                    voice.track = None
            self._effect_channel.set_volume(self._sfx_volume)
            for voice in self._cue_voices:
                voice.channel.set_volume(self._sfx_volume)
        except (RuntimeError, self.pg.error):
            # SDL can lose an audio device during play; presentation still runs.
            self._failed = True
            self._retry_at = self._clock + RETRY_SECONDS
            self._silence()

    def play_cue(
        self, cue: str, *, enabled: bool | None = None, volume: float | None = None,
    ) -> bool:
        """Play a story cue through the same volume, mute, and device controls.

        Passing current UI preferences is useful for queued story events: a
        cue emitted just before the player muted sound stays muted. A cue can
        play on the main menu, even before the first ambience update.
        """

        audible = self._enabled if enabled is None else bool(enabled)
        level = self._sfx_volume if volume is None else _volume(volume)
        cue = cue if cue in SoundPlayer.CUES else "notice"
        cooldown = 0.15 if cue == "notice" else 0.35
        if not audible or level == 0.0 or self._clock - self._last_cue.get(cue, -math.inf) < cooldown:
            return False
        if not self._ensure_mixer():
            return False
        try:
            if cue not in self._cue_sounds:
                self._cue_sounds[cue] = self.pg.mixer.Sound(str(self.asset_dir / SoundPlayer.CUES[cue]))
            voice = next((voice for voice in self._cue_voices if not voice.channel.get_busy()), None)
            if voice is None:
                voice = min(self._cue_voices, key=lambda candidate: candidate.priority)
                if CUE_PRIORITY[cue] <= voice.priority:
                    return False
            voice.channel.set_volume(level)
            voice.channel.play(self._cue_sounds[cue])
            voice.cue = cue
            voice.priority = CUE_PRIORITY[cue]
            self._last_cue[cue] = self._clock
        except (OSError, RuntimeError, self.pg.error):
            return False
        return True

    def play_effect(self, effect: str, *, surface: str | None = None) -> bool:
        """Play a quiet cached interaction or visible battle impact.

        Effects share one bounded channel. Interface hover cannot cut off a
        battle sound; simultaneous impacts keep the more meaningful reaction.
        Neither the ambience nor story-cue channels are restarted.
        """

        if (
            effect not in EFFECT_COOLDOWNS
            or not self._enabled
            or self._sfx_volume == 0.0
            or self._desired is None
            or self._clock - self._last_effect.get(effect, -math.inf) < EFFECT_COOLDOWNS[effect]
            or not self._ensure_mixer()
        ):
            return False
        if surface is None:
            surface = "wood" if self._desired == "tavern" else "grass" if self._desired == "outdoors" else "stone"
        if surface not in {"wood", "stone", "mud", "grass"}:
            surface = "stone"
        variant = self._footstep_number % 2 if effect == "footstep" else 0
        key = f"footstep:{surface}:{variant}" if effect == "footstep" else effect
        try:
            if self._effect_channel.get_busy():
                priority = EFFECT_PRIORITY[effect]
                current_priority = EFFECT_PRIORITY.get(self._effect_playing, 0)
                if effect == "footstep" or priority < current_priority:
                    return False
                if effect in BATTLE_EFFECTS and priority <= current_priority and self._clock - self._last_effect.get("_battle", -math.inf) < 0.04:
                    return False
            if key not in self._effects:
                self._effects[key] = self.pg.mixer.Sound(file=io.BytesIO(_effect_wave(effect, surface=surface, variant=variant)))
            self._effect_channel.set_volume(self._sfx_volume)
            self._effect_channel.play(self._effects[key])
            self._effect_playing = effect
            self._last_effect[effect] = self._clock
            if effect in BATTLE_EFFECTS:
                self._last_effect["_battle"] = self._clock
            if effect == "footstep":
                self._footstep_number += 1
        except (OSError, RuntimeError, self.pg.error):
            return False
        return True

    def _silence(self) -> None:
        self._effect_playing = None
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
        for voice in self._cue_voices:
            try:
                voice.channel.stop()
            except (RuntimeError, self.pg.error):
                pass
            voice.cue = None
            voice.priority = -1
        self._duck = 1.0
        self._music_level = None

    def stop(self) -> None:
        """Stop owned channels without stopping unrelated cues or quitting SDL."""

        self._desired = None
        self._enabled = False
        self._silence()


def _effect_wave(effect: str, *, surface: str = "stone", variant: int = 0) -> bytes:
    """Small deterministic, original sounds; generated once and cached by SDL."""

    if effect in BATTLE_EFFECTS:
        return _battle_effect_wave(effect)
    sample_rate = 16_000
    duration = {"footstep": 0.085, "interact": 0.16, "hover": 0.055}[effect]
    rng = random.Random(1789 + variant % 2 * 17)
    data = bytearray()
    low_noise = 0.0
    coefficient, frequency, noise_gain, tone_gain, step_amplitude = {
        "wood": (0.16, 112, 0.48, 0.36, 2_000),
        "stone": (0.38, 156, 0.68, 0.18, 1_750),
        "mud": (0.07, 75, 0.82, 0.18, 2_050),
        "grass": (0.12, 98, 0.84, 0.10, 1_700),
    }.get(surface, (0.38, 156, 0.68, 0.18, 1_750))
    for index in range(round(duration * sample_rate)):
        t = index / sample_rate
        envelope = min(1.0, t / 0.005) * (1.0 - t / duration) ** 2
        if effect == "footstep":
            amplitude = step_amplitude
            low_noise += (rng.uniform(-1.0, 1.0) - low_noise) * coefficient
            value = (low_noise * noise_gain + math.sin(math.tau * (frequency + variant % 2 * 6) * t) * tone_gain) * envelope
        elif effect == "interact":
            value = (math.sin(math.tau * 523.25 * t) + 0.35 * math.sin(math.tau * 784 * t)) * envelope
            amplitude = 2_100
        else:
            value = math.sin(math.tau * 660 * t) * envelope
            amplitude = 850
        sample = round(value * amplitude)
        pan = (-0.06 if variant % 2 == 0 else 0.06) if effect == "footstep" else 0.0
        data.extend(struct.pack("<hh", round(sample * (1.0 - pan)), round(sample * (1.0 + pan))))
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(data)
    return stream.getvalue()


def _battle_effect_wave(effect: str) -> bytes:
    """Original soft impacts, resonances, and wind with matched quiet levels."""

    sample_rate = 16_000
    duration = BATTLE_EFFECTS[effect]
    rng = random.Random(3127 + list(BATTLE_EFFECTS).index(effect) * 107)
    values: list[float] = []
    low_noise = 0.0
    for index in range(round(duration * sample_rate)):
        t = index / sample_rate
        noise = rng.uniform(-1.0, 1.0)
        low_noise += (noise - low_noise) * 0.11
        envelope = min(1.0, t / 0.008) * (1.0 - t / duration) ** 1.6
        if effect == "hit":
            value = 0.48 * math.sin(math.tau * 120 * t) + 0.24 * math.sin(math.tau * 780 * t) * math.exp(-35 * t) + 0.3 * noise * math.exp(-25 * t)
        elif effect == "block":
            value = 0.55 * math.sin(math.tau * 230 * t) + 0.25 * math.sin(math.tau * 713 * t) + 0.2 * noise * math.exp(-50 * t)
        elif effect == "hurt":
            value = 0.65 * math.sin(math.tau * 80 * t) + 0.15 * math.sin(math.tau * 160 * t) + 0.4 * low_noise
        elif effect == "heal":
            envelope = math.sin(math.pi * t / duration) ** 1.2
            value = 0.6 * math.sin(math.tau * 523.25 * t) + 0.4 * math.sin(math.tau * 659.25 * t)
        elif effect == "guard":
            value = 0.65 * math.sin(math.tau * 196 * t) + 0.25 * math.sin(math.tau * 392 * t) + 0.15 * low_noise
        elif effect == "evade":
            envelope = math.sin(math.pi * t / duration) ** 1.2
            value = 0.75 * (noise - low_noise) + 0.2 * low_noise
        elif effect == "interrupt":
            value = 0.5 * math.sin(math.tau * 440 * t) + 0.25 * math.sin(math.tau * 1030 * t) + 0.25 * noise * math.exp(-30 * t)
        elif effect == "fall":
            value = 0.65 * math.sin(math.tau * (110 * t - 75 * t * t)) + 0.25 * low_noise + 0.15 * math.sin(math.tau * 330 * t) * math.exp(-20 * t)
        else:  # escape: a soft rising breath, rather than a second victory cue
            envelope = math.sin(math.pi * t / duration) ** 1.4
            value = 0.6 * math.sin(math.tau * (330 * t + 90 * t * t)) + 0.4 * low_noise
        values.append(value * envelope)
    peak = max(map(abs, values), default=1.0)
    rms = math.sqrt(sum(value * value for value in values) / max(1, len(values)))
    gain = min(0.08 / max(peak, 1e-9), 10 ** (-32 / 20) / max(rms, 1e-9))
    data = b"".join(struct.pack("<hh", sample, sample) for value in values for sample in [round(value * gain * 32767)])
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(data)
    return stream.getvalue()
