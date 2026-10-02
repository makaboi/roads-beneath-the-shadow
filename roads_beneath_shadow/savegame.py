"""JSON save slots with atomic writes and lightweight metadata."""

from __future__ import annotations

import json
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import VALID_SCENE_IDS, GameState


MAX_SAVE_BYTES = 2_000_000


def default_save_directory() -> Path:
    override = os.environ.get("RBS_SAVE_DIR")
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Roads Beneath the Shadow" / "saves"
    return Path.home() / ".roads_beneath_shadow" / "saves"


class SaveManager:
    SLOT_COUNT = 3

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_save_directory()

    def _path(self, slot: int) -> Path:
        if not 1 <= slot <= self.SLOT_COUNT:
            raise ValueError(f"Save slot must be between 1 and {self.SLOT_COUNT}")
        return self.root / f"slot_{slot}.json"

    def save(self, slot: int, state: GameState) -> Path:
        if not isinstance(state, GameState):
            raise ValueError("state must be a GameState")
        serialized_state = state.to_dict()
        validated_state = GameState.from_dict(serialized_state)
        self._validate_state(validated_state)
        path = self._path(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "state": serialized_state,
        }
        handle, temporary_name = tempfile.mkstemp(prefix=f"slot_{slot}_", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as temporary:
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return path

    def load(self, slot: int) -> GameState:
        path = self._path(slot)
        if path.stat().st_size > MAX_SAVE_BYTES:
            raise ValueError("Save file is too large")
        try:
            with path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
        except RecursionError as error:
            raise ValueError("Save file is too deeply nested") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
            raise ValueError("Save file is malformed")
        state = GameState.from_dict(payload["state"])
        self._validate_state(state)
        return state

    def delete(self, slot: int) -> None:
        self._path(slot).unlink(missing_ok=True)

    def slot_metadata(self, slot: int) -> dict[str, Any] | None:
        path = self._path(slot)
        if not path.exists():
            return None
        try:
            state = self.load(slot)
            return {
                "slot": slot,
                "name": state.character.name,
                "origin": state.character.origin,
                "chapter": state.chapter,
                "scene": state.scene,
                "ending": state.ending,
                "saved_at": self._saved_at(path),
            }
        except (OSError, KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return {"slot": slot, "corrupt": True}

    def all_slots(self) -> list[dict[str, Any] | None]:
        return [self.slot_metadata(slot) for slot in range(1, self.SLOT_COUNT + 1)]

    @staticmethod
    def _saved_at(path: Path) -> str:
        with path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
        saved_at = payload.get("saved_at", "unknown")
        return saved_at if isinstance(saved_at, str) else "unknown"

    @staticmethod
    def _validate_state(state: GameState) -> None:
        """Validate semantic constraints that depend on the game's content catalog."""
        from .content import ENDING_TEXT, ITEMS, ORIGINS, PART_ONE_ENDINGS

        character = state.character
        origin_ids = {origin.origin_id for origin in ORIGINS}
        if character.origin not in origin_ids:
            raise ValueError(f"Unknown character origin: {character.origin}")

        if not 1 <= character.max_hp <= 10_000:
            raise ValueError("character.max_hp must be between 1 and 10000")
        if not 0 <= character.hp <= character.max_hp:
            raise ValueError("character.hp must be between 0 and character.max_hp")
        if not 1 <= character.max_focus <= 1_000:
            raise ValueError("character.max_focus must be between 1 and 1000")
        if not 0 <= character.focus <= character.max_focus:
            raise ValueError("character.focus must be between 0 and character.max_focus")

        bounded_stats = {
            "strength": character.strength,
            "cunning": character.cunning,
            "will": character.will,
            "hope": character.hope,
            "corruption": character.corruption,
            "mara_trust": character.mara_trust,
            "tobin_trust": character.tobin_trust,
        }
        for name, value in bounded_stats.items():
            if not -10_000 <= value <= 10_000:
                raise ValueError(f"character.{name} is outside the supported range")

        for item_id, quantity in character.inventory.items():
            if item_id not in ITEMS:
                raise ValueError(f"Unknown inventory item: {item_id}")
            if not 1 <= quantity <= 1_000:
                raise ValueError(f"Inventory quantity for {item_id} must be between 1 and 1000")

        equipment = (("weapon", character.weapon), ("armor", character.armor))
        for slot, item_id in equipment:
            if item_id is None:
                continue
            item = ITEMS.get(item_id)
            if item is None:
                raise ValueError(f"Unknown equipped {slot}: {item_id}")
            if item_id not in character.inventory:
                raise ValueError(f"Equipped {slot} is not present in inventory: {item_id}")
            if item.slot != slot:
                raise ValueError(f"Equipped item {item_id} cannot be used as {slot}")

        if state.ending is not None and state.ending not in ENDING_TEXT:
            raise ValueError(f"Unknown ending: {state.ending}")
        if state.scene not in VALID_SCENE_IDS:
            raise ValueError(f"Unknown scene: {state.scene}")
        if (state.scene == "complete") != (state.ending is not None):
            raise ValueError("scene must be 'complete' if and only if an ending is set")
        if not 1 <= state.chapter <= 1_000:
            raise ValueError("chapter must be between 1 and 1000")
        if state.scene.startswith("part2_") and state.chapter != 2:
            raise ValueError("Part II scenes require chapter 2")
        if state.scene != "complete" and not state.scene.startswith("part2_") and state.chapter != 1:
            raise ValueError("Part I scenes require chapter 1")
        if state.ending in PART_ONE_ENDINGS and state.chapter != 1:
            raise ValueError("Part I endings require chapter 1")
        if state.ending is not None and state.ending not in PART_ONE_ENDINGS and state.chapter != 2:
            raise ValueError("Part II endings require chapter 2")
        if not 0 <= state.play_minutes <= 10_000_000:
            raise ValueError("play_minutes must be between 0 and 10000000")
