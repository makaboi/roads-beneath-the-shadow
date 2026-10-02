"""Persistent player preferences for the terminal presentation and difficulty."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .savegame import default_save_directory


SETTINGS_VERSION = 1
COLOR_MODES = {"auto", "on", "off"}
TEXT_SPEEDS = {"slow", "normal", "fast", "instant"}
DIFFICULTIES = {"story", "ranger", "shadow"}


@dataclass
class UserSettings:
    """Preferences that should survive between launches but never affect saves."""

    color_mode: str = "auto"
    sound: bool = False
    text_speed: str = "normal"
    reduced_motion: bool = False
    screen_reader: bool = False
    difficulty: str = "ranger"
    autosave: bool = True
    music_volume: float = 0.25
    sfx_volume: float = 0.6
    version: int = SETTINGS_VERSION

    def validate(self) -> "UserSettings":
        if not isinstance(self.color_mode, str) or self.color_mode not in COLOR_MODES:
            self.color_mode = "auto"
        if not isinstance(self.text_speed, str) or self.text_speed not in TEXT_SPEEDS:
            self.text_speed = "normal"
        if not isinstance(self.difficulty, str) or self.difficulty not in DIFFICULTIES:
            self.difficulty = "ranger"
        if not isinstance(self.sound, bool):
            self.sound = False
        if not isinstance(self.reduced_motion, bool):
            self.reduced_motion = False
        if not isinstance(self.screen_reader, bool):
            self.screen_reader = False
        if not isinstance(self.autosave, bool):
            self.autosave = True
        for field_name, default in (("music_volume", 0.25), ("sfx_volume", 0.6)):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 or not math.isfinite(value):
                value = default
            setattr(self, field_name, float(value))
        self.version = SETTINGS_VERSION
        return self

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserSettings":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        clean = {key: value for key, value in payload.items() if key in allowed}
        try:
            return cls(**clean).validate()
        except (TypeError, ValueError):
            return cls()


class SettingsManager:
    """Load and atomically store player preferences."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_save_directory().parent / "settings.json"

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        try:
            with self.path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
            if not isinstance(payload, dict):
                return UserSettings()
            return UserSettings.from_dict(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return UserSettings()

    def save(self, settings: UserSettings) -> Path:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix="settings_", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temporary:
                json.dump(asdict(settings), temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return self.path
