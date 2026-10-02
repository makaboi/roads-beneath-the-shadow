"""Persistent, save-independent completion records and achievements."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .content import ENDING_TEXT, ORIGINS, PART_ONE_ENDINGS
from .models import GameState
from .savegame import MAX_SAVE_BYTES, default_save_directory


PROFILE_VERSION = 1

ACHIEVEMENTS = {
    "part_one": "The Road Opens — Complete Part I.",
    "none_left_behind": "None Left Behind — Save Ned and keep both companions on the road.",
    "unbroken_hope": "A Light in Dark Places — Finish with Hope far stronger than Corruption.",
    "shadow_touched": "The Shadow Knows You — Finish while carrying deep Corruption.",
    "road_scholar": "Keeper of Signs — Recover twelve or more journal clues.",
    "many_roads": "Many Roads — Complete Part I with every origin.",
    "fates_witnessed": "Fates Witnessed — Discover four different Part I endings.",
    "part_two": "The Dead Road — Complete Part II.",
    "names_remembered": "Names Remembered — Recover all three Warden testimonies.",
    "none_forsaken": "None Forsaken — Rescue the prisoners and keep every available companion alive.",
    "no_name_for_shadow": "No Name for the Shadow — Reach the Living Road without accepting the star's power.",
}

@dataclass
class PlayerProfile:
    completed_runs: int = 0
    endings: dict[str, int] = field(default_factory=dict)
    origins_completed: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    recorded_journeys: list[str] = field(default_factory=list)
    version: int = PROFILE_VERSION

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, strict: bool = False) -> "PlayerProfile":
        try:
            if not isinstance(payload, dict):
                raise ValueError("Completion record must be an object")
            if strict:
                _validate_profile_fields(payload)
            valid_origins = {origin.origin_id for origin in ORIGINS}
            endings = {
                str(name): max(0, int(count))
                for name, count in dict(payload.get("endings", {})).items()
                if isinstance(name, str) and name in ENDING_TEXT
            }
            origins = list(
                dict.fromkeys(
                    value
                    for value in payload.get("origins_completed", [])
                    if isinstance(value, str) and value in valid_origins
                )
            )
            achievements = [
                value
                for value in dict.fromkeys(str(value) for value in payload.get("achievements", []))
                if value in ACHIEVEMENTS
            ]
            recorded = list(
                dict.fromkeys(
                    str(value)
                    for value in payload.get("recorded_journeys", [])
                    if isinstance(value, str)
                    and 1 <= len(value) <= 138
                    and value.isprintable()
                )
            )
            return cls(
                completed_runs=max(0, int(payload.get("completed_runs", 0))),
                endings=endings,
                origins_completed=origins,
                achievements=achievements,
                recorded_journeys=recorded,
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            if strict:
                raise ValueError("Completion record has invalid fields") from error
            return cls()

    def unlock(self, achievement: str) -> bool:
        if achievement not in ACHIEVEMENTS or achievement in self.achievements:
            return False
        self.achievements.append(achievement)
        return True

    def record(self, state: GameState) -> list[str]:
        if not state.ending:
            raise ValueError("Cannot record a journey before it has an ending")
        journey_id = getattr(state, "journey_id", "")
        record_key = f"{journey_id}:part_{state.chapter}" if journey_id else ""
        legacy_part_one_recorded = state.chapter == 1 and journey_id in self.recorded_journeys
        if record_key and (record_key in self.recorded_journeys or legacy_part_one_recorded):
            return []
        if record_key:
            self.recorded_journeys.append(record_key)
        self.completed_runs += 1
        self.endings[state.ending] = self.endings.get(state.ending, 0) + 1
        if state.character.origin not in self.origins_completed:
            self.origins_completed.append(state.character.origin)

        if state.chapter == 2:
            candidates = ["part_two"]
            if all(
                state.flags.get(flag, False)
                for flag in (
                    "part2_testimony_first",
                    "part2_testimony_second",
                    "part2_testimony_third",
                )
            ):
                candidates.append("names_remembered")
            if state.flags.get("part2_prisoners_rescued") and state.flags.get(
                "part_two_mara_present"
            ):
                candidates.append("none_forsaken")
            star_power_flags = (
                "accepted_star_power",
                "used_star_in_final",
                "part2_star_commanded",
                "part2_star_guided_descent",
                "part2_spoke_hidden_name",
                "part2_star_read_memory",
                "part2_star_broke_chain",
                "part2_star_bargain",
                "part2_descent_mark_bargain",
            )
            if (
                state.ending == "living_road"
                and state.flags.get("part2_star_rejected")
                and not any(state.flags.get(flag, False) for flag in star_power_flags)
            ):
                candidates.append("no_name_for_shadow")
        else:
            candidates = ["part_one"]
            if (
                state.flags.get("ned_survived")
                and state.flags.get("mara_chose_to_continue")
                and state.flags.get("tobin_chose_to_continue")
            ):
                candidates.append("none_left_behind")
            if state.character.hope >= state.character.corruption + 3:
                candidates.append("unbroken_hope")
            if state.character.corruption >= 3:
                candidates.append("shadow_touched")
            if len(state.journal) >= 12:
                candidates.append("road_scholar")
            if len(self.origins_completed) >= 3:
                candidates.append("many_roads")
            if sum(self.endings.get(ending, 0) > 0 for ending in PART_ONE_ENDINGS) >= 4:
                candidates.append("fates_witnessed")
        return [achievement for achievement in candidates if self.unlock(achievement)]


def _validate_profile_fields(payload: dict[str, Any]) -> None:
    """Accept missing legacy fields while rejecting damaged JSON structures."""

    def count(value: Any, field_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a nonnegative integer")

    count(payload.get("completed_runs", 0), "completed_runs")
    if "version" in payload:
        count(payload["version"], "version")
        if payload["version"] != PROFILE_VERSION:
            raise ValueError("Unsupported completion record version")
    endings = payload.get("endings", {})
    if not isinstance(endings, dict):
        raise ValueError("endings must be an object")
    for ending, value in endings.items():
        count(value, f"endings.{ending}")
    for field_name in ("origins_completed", "achievements", "recorded_journeys"):
        values = payload.get(field_name, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"{field_name} must be a list of strings")


class ProfileManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_save_directory().parent / "profile.json"
        self.last_load_error: str | None = None
        self.last_recovery_backup: Path | None = None
        self._last_load_exception: Exception | None = None

    def load(self) -> PlayerProfile:
        self.last_load_error = None
        self._last_load_exception = None
        try:
            if self.path.stat().st_size > MAX_SAVE_BYTES:
                raise ValueError("Completion record file is too large")
            with self.path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
            if not isinstance(payload, dict):
                raise ValueError("Completion record must be an object")
            return PlayerProfile.from_dict(payload, strict=True)
        except FileNotFoundError:
            return PlayerProfile()
        except (OSError, TypeError, ValueError, RecursionError) as error:
            self.last_load_error = str(error)
            self._last_load_exception = error
            return PlayerProfile()

    def save(self, profile: PlayerProfile) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix="profile_", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temporary:
                json.dump(asdict(profile), temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return self.path

    def record(self, state: GameState) -> list[str]:
        self.last_recovery_backup = None
        profile = self.load()
        if isinstance(self._last_load_exception, OSError):
            raise self._last_load_exception
        unlocked = profile.record(state)
        if self._last_load_exception is not None:
            self.last_recovery_backup = self._preserve_damaged_record()
        self.save(profile)
        return unlocked

    def _preserve_damaged_record(self) -> Path:
        """Keep exact damaged bytes before replacing a record with fresh progress."""

        handle, temporary_name = tempfile.mkstemp(
            prefix=f"{self.path.stem}.damaged.", suffix=".json", dir=self.path.parent
        )
        backup = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as target, self.path.open("rb") as source:
                shutil.copyfileobj(source, target)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        return backup
