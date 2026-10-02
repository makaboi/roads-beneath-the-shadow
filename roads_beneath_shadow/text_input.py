"""Small source-preserving text editor shared by desktop input fields.

This module owns no SDL state. Renderers decide focus, composition, and how to
draw the caret; committed text and selections use Python character offsets.
"""

from __future__ import annotations

from unicodedata import category


class TextEntry:
    """A bounded one-line editor with a caret and an optional selection."""

    def __init__(self, text: str = "", *, max_length: int = 64) -> None:
        self.max_length = max(0, int(max_length))
        self.text = ""
        self.cursor = 0
        self.anchor: int | None = None
        self.set_text(text)

    @staticmethod
    def _printable(text: str) -> str:
        # Pasted line breaks separate words rather than silently joining them.
        return "".join(" " if character.isspace() and not character.isprintable() else character for character in str(text) if character.isprintable() or character.isspace())

    @property
    def selection(self) -> tuple[int, int]:
        return tuple(sorted((self.cursor, self.anchor))) if self.anchor is not None else (self.cursor, self.cursor)

    @property
    def has_selection(self) -> bool:
        return self.anchor is not None and self.anchor != self.cursor

    def set_text(self, text: str, *, cursor: int | None = None, select: bool = False) -> None:
        self.text = self._printable(text)[:self.max_length]
        self.cursor = len(self.text) if cursor is None else max(0, min(len(self.text), int(cursor)))
        self.anchor = 0 if select else None

    def select_all(self) -> None:
        self.cursor = len(self.text)
        self.anchor = 0

    def clear_selection(self) -> None:
        self.anchor = None

    def move_to(self, position: int, *, select: bool = False) -> None:
        position = max(0, min(len(self.text), int(position)))
        # A combining accent stays with its base when placing a caret.
        while position > 0 and position < len(self.text) and category(self.text[position]).startswith("M"):
            position -= 1
        if select and self.anchor is None:
            self.anchor = self.cursor
        elif not select:
            self.anchor = None
        self.cursor = position

    def home(self, select: bool = False) -> None:
        self.move_to(0, select=select)

    def end(self, select: bool = False) -> None:
        self.move_to(len(self.text), select=select)

    def _previous(self, position: int) -> int:
        position = max(0, position - 1)
        while position > 0 and category(self.text[position]).startswith("M"):
            position -= 1
        return position

    def _next(self, position: int) -> int:
        position = min(len(self.text), position + 1)
        while position < len(self.text) and category(self.text[position]).startswith("M"):
            position += 1
        return position

    @staticmethod
    def _word_kind(character: str) -> str:
        return "space" if character.isspace() else "word" if character.isalnum() or character == "_" or category(character).startswith("M") else "punctuation"

    def _word_boundary(self, direction: int) -> int:
        position = self.cursor
        if direction < 0:
            while position and self.text[position - 1].isspace():
                position = self._previous(position)
            kind = self._word_kind(self.text[position - 1]) if position else ""
            while position and self._word_kind(self.text[position - 1]) == kind:
                position = self._previous(position)
        else:
            kind = self._word_kind(self.text[position]) if position < len(self.text) else ""
            while position < len(self.text) and self._word_kind(self.text[position]) == kind:
                position = self._next(position)
            while position < len(self.text) and self.text[position].isspace():
                position = self._next(position)
        return position

    def navigate(self, direction: int, *, select: bool = False, word: bool = False) -> None:
        if not direction:
            return
        if self.has_selection and not select:
            position = self.selection[0 if direction < 0 else 1]
        else:
            position = self._word_boundary(direction) if word else self._previous(self.cursor) if direction < 0 else self._next(self.cursor)
        self.move_to(position, select=select)

    def insert(self, text: str) -> bool:
        start, end = self.selection
        value = self._printable(text)[:max(0, self.max_length - len(self.text) + end - start)]
        if not value:
            return False
        previous = self.text
        self.text = self.text[:start] + value + self.text[end:]
        self.cursor = start + len(value)
        self.anchor = None
        return self.text != previous

    def _remove(self, start: int, end: int) -> bool:
        if start == end:
            return False
        self.text = self.text[:start] + self.text[end:]
        self.cursor = start
        self.anchor = None
        return True

    def backspace(self, word: bool = False) -> bool:
        start, end = self.selection
        return self._remove(start, end) if self.has_selection else self._remove(self._word_boundary(-1) if word else self._previous(self.cursor), self.cursor)

    def delete(self, word: bool = False) -> bool:
        start, end = self.selection
        return self._remove(start, end) if self.has_selection else self._remove(self.cursor, self._word_boundary(1) if word else self._next(self.cursor))
