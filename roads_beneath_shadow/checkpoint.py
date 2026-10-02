"""A separate automatic checkpoint using the manual saves' validated format.

The game decides when a scene transition is safe to record.  This module only
stores a complete GameState; it never captures in-progress combat or changes a
manual save slot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import GameState
from .savegame import SaveManager


_READ_ERRORS = (OSError, KeyError, TypeError, UnicodeError, ValueError, RecursionError)


class CheckpointManager(SaveManager):
    """One private checkpoint, with atomic writes and duplicate suppression.

    ``record`` and ``resume`` deliberately propagate storage/validation errors
    so the game can report a failed save or resume.  ``metadata`` is safe for
    the main menu: a missing checkpoint returns None and a damaged or unreadable
    one returns ``{"corrupt": True}``.
    """

    SLOT_COUNT = 1

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root)
        self._last_signature: str | None = None
        self._last_file: tuple[int, int, int] | None = None

    @property
    def path(self) -> Path:
        return self.root / "checkpoint.json"

    def _path(self, slot: int) -> Path:
        if slot != 1:
            raise ValueError("The automatic checkpoint has only one private slot")
        return self.path

    @staticmethod
    def _signature(state: GameState) -> str:
        return json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _file_stamp(self) -> tuple[int, int, int] | None:
        try:
            status = self.path.stat()
            return status.st_mtime_ns, status.st_size, status.st_ino
        except OSError:
            return None

    def _remember_existing(self, stamp: tuple[int, int, int] | None) -> None:
        """Recognize unchanged checkpoints after restarting the application."""

        if stamp is None:
            return
        try:
            existing = super().load(1)
        except _READ_ERRORS:
            return
        if self._file_stamp() == stamp:
            self._last_signature = self._signature(existing)
            self._last_file = stamp

    def record(self, state: GameState) -> Path:
        """Atomically record a validated state, skipping identical contents.

        Normalizing through GameState.from_dict also ensures a migrated older
        in-memory state is written in the current version-two format.  The
        deduplication signature excludes the save envelope's timestamp.
        """

        if not isinstance(state, GameState):
            raise ValueError("state must be a GameState")
        validated = GameState.from_dict(state.to_dict())
        self._validate_state(validated)
        signature = self._signature(validated)
        stamp = self._file_stamp()
        if stamp != self._last_file:
            self._last_signature = None
            self._last_file = None
        if self._last_signature is None:
            self._remember_existing(stamp)
        if stamp is not None and self._last_file == stamp and self._last_signature == signature:
            return self.path
        # SaveManager validates the entire state and replaces the destination
        # only after its temporary file has been written successfully.
        path = super().save(1, validated)
        self._last_signature = signature
        self._last_file = self._file_stamp()
        return path

    def resume(self) -> GameState:
        """Load the checkpoint with the same migrations as a manual save."""

        stamp = self._file_stamp()
        state = super().load(1)
        if stamp is not None and self._file_stamp() == stamp:
            self._last_signature = self._signature(state)
            self._last_file = stamp
        else:
            self._last_signature = None
            self._last_file = None
        return state

    def metadata(self) -> dict[str, Any] | None:
        """Return a validated menu summary, without a manual-slot identity."""

        try:
            metadata = super().slot_metadata(1)
        except _READ_ERRORS:
            return {"corrupt": True}
        if metadata is None:
            return None
        return {key: value for key, value in metadata.items() if key != "slot"}

    def clear(self) -> None:
        """Remove only the checkpoint after an explicit discard decision."""

        try:
            super().delete(1)
        finally:
            self._last_signature = None
            self._last_file = None
