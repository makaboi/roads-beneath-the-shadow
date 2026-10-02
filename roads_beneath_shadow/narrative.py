"""Chronological story presentation without a graphical or engine dependency.

The engine may emit several illustrations and paragraphs before it asks for
input.  This director retains that sequence while the engine waits: a renderer
can advance local pages without answering the engine's pending request.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any


WrapText = Callable[[str], Sequence[str]]


@dataclass(frozen=True)
class StoryText:
    """A paragraph or measured display line, retaining its original emphasis."""

    text: str
    color: Any = None
    bold: bool = False
    narration: bool = False


@dataclass(frozen=True)
class StoryBeat:
    """Text and heading associated with one illustration in story order."""

    heading: str
    scene_text: str
    scene_caption: str | None
    scene_color: Any
    paragraphs: tuple[StoryText, ...]

    @property
    def has_narration(self) -> bool:
        return any(paragraph.narration for paragraph in self.paragraphs)

    @property
    def text(self) -> str:
        return "\n".join(paragraph.text for paragraph in self.paragraphs)


@dataclass(frozen=True)
class NarrativePage:
    """A page that fits a measured number of rows and remembers its source."""

    heading: str
    scene_text: str
    scene_caption: str | None
    scene_color: Any
    lines: tuple[StoryText, ...]
    beat_index: int
    number: int = 1
    total: int = 1
    # The normalized character offset makes resize reflow independent of the
    # old wrapping width.  It refers to (beat, paragraph, character).
    start: tuple[int, int, int] = (0, 0, 0)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class _MeasuredLine:
    content: StoryText
    paragraph: int
    offset: int


class NarrativeDirector:
    """Collect UI events, paginate a prompt, and retain the reading position.

    ``feed(event)`` accepts the existing UIEvent shape, while ``record(kind,
    **data)`` is convenient for callers without that class.  At an engine input
    request, call ``prepare(request, wrap=..., rows=...)``.  ``has_next`` means
    the renderer should offer Continue instead of submitting engine input;
    the final page can display the actual choices alongside its text.

    ``cinematic=False`` gives menus and utility panels one static context page.
    An explicit value takes precedence over the conservative automatic mode.
    The transcript belongs to the renderer and is never cleared or altered by
    this object.
    """

    def __init__(self) -> None:
        self.heading = "THE ROAD AWAITS"
        self.scene_text = ""
        self.scene_caption: str | None = None
        self.scene_color: Any = None
        self.beats: tuple[StoryBeat, ...] = ()
        self.pages: tuple[NarrativePage, ...] = ()
        self.index = 0
        self._pending_beats: list[StoryBeat] = []
        self._paragraphs: list[StoryText] = []
        self._new_art = False
        self._cinematic = False
        self._suppressed_headers: frozenset[str] = frozenset()

    @property
    def current(self) -> NarrativePage | None:
        return self.pages[self.index] if self.pages else None

    @property
    def has_next(self) -> bool:
        return self.index + 1 < len(self.pages)

    @property
    def has_previous(self) -> bool:
        return bool(self.pages and self.index > 0)

    @property
    def cinematic(self) -> bool:
        return self._cinematic

    def feed(self, event: Any) -> None:
        """Accept an object with ``kind``/``data`` or a mapping of those keys."""

        if isinstance(event, Mapping):
            self.record(str(event["kind"]), **event.get("data", {}))
        else:
            self.record(event.kind, **event.data)

    def record(self, kind: str, **data: Any) -> None:
        if kind == "clear":
            self._seal()
            self.heading = "THE ROAD AWAITS"
        elif kind == "title":
            if self._paragraphs:
                self._seal()
            self.heading = str(data.get("text", "")).strip()
        elif kind == "art":
            self._seal()
            self.scene_text = str(data.get("text", ""))
            self.scene_caption = data.get("alt_text")
            self.scene_color = data.get("color")
            self._new_art = True
        elif kind == "text":
            self._paragraphs.append(
                StoryText(
                    str(data.get("text", "")),
                    data.get("color"),
                    bool(data.get("bold", False)),
                    bool(data.get("narration", False)),
                )
            )

    def _seal(self) -> None:
        paragraphs = tuple(self._paragraphs)
        # A meaningful illustration with no intervening prose still deserves
        # its place in the sequence: the Prancing Pony interior is one example.
        # Empty/decorative artwork does not create a blank Continue screen.
        if not any(paragraph.text.strip() for paragraph in paragraphs):
            caption = (self.scene_caption or "").strip()
            if self._new_art and caption and caption != "The road continues beneath the shadow.":
                paragraphs = (StoryText(caption, self.scene_color),)
            else:
                paragraphs = ()
        if paragraphs:
            self._pending_beats.append(
                StoryBeat(
                    self.heading,
                    self.scene_text,
                    self.scene_caption,
                    self.scene_color,
                    paragraphs,
                )
            )
        self._paragraphs.clear()
        self._new_art = False

    def prepare(
        self,
        request: Any = None,
        *,
        wrap: WrapText,
        rows: int,
        cinematic: bool | None = None,
        suppress_headers: Iterable[str] = (),
    ) -> tuple[NarrativePage, ...]:
        """Finish pending beats and measure pages for the new engine request.

        Consecutive prompts without new output retain the previous final page,
        rather than replaying the whole scene after an engine pause.  Headers
        in ``suppress_headers`` omit only those beats from displayed pages;
        their complete source remains available in ``beats``.  This lets a
        structured combat panel replace terminal combat readouts while the
        preceding story still receives its proper illustrated pages.
        """

        self._seal()
        pending = tuple(self._pending_beats)
        self._pending_beats.clear()
        self._suppressed_headers = frozenset(str(header).strip().casefold() for header in suppress_headers)
        if not pending:
            previous = self.pages[-1] if self.pages else None
            self.pages = (replace(previous, number=1, total=1),) if previous else ()
            self.index = 0
            self._cinematic = False
            return self.pages
        self.beats = pending
        self._cinematic = (
            bool(cinematic)
            if cinematic is not None
            else self._should_present_narrative(request, pending)
        )
        self.pages = self._paginate(wrap, rows)
        self.index = 0
        return self.pages

    @staticmethod
    def _should_present_narrative(request: Any, beats: Sequence[StoryBeat]) -> bool:
        if not any(beat.has_narration for beat in beats):
            return False
        label = str(getattr(request, "label", "")).strip().casefold()
        heading = beats[-1].heading.strip().casefold()
        if heading in {"combat", "inventory", "journal", "settings"}:
            return False
        if label in {
            "main menu",
            "choose your action",
            "change target",
            "inventory actions",
            "equip which item?",
            "use which item?",
            "choose a save slot",
            "load which journey?",
        }:
            return False
        return True

    @staticmethod
    def _measure(beat: StoryBeat, wrap: WrapText) -> list[_MeasuredLine]:
        measured: list[_MeasuredLine] = []
        for index, paragraph in enumerate(beat.paragraphs):
            normalized = " ".join(paragraph.text.split())
            cursor = 0
            for line in wrap(paragraph.text):
                text = str(line)
                normalized_line = " ".join(text.split())
                offset = normalized.find(normalized_line, cursor) if normalized_line else cursor
                if offset < 0:
                    offset = cursor
                measured.append(
                    _MeasuredLine(replace(paragraph, text=text), index, offset)
                )
                cursor = offset + len(normalized_line)
                if normalized[cursor:cursor + 1] == " ":
                    cursor += 1
        return measured

    def _paginate(self, wrap: WrapText, rows: int) -> tuple[NarrativePage, ...]:
        capacity = max(1, int(rows))
        pages: list[NarrativePage] = []
        for beat_index, beat in enumerate(self.beats):
            if beat.heading.strip().casefold() in self._suppressed_headers:
                continue
            lines = self._measure(beat, wrap)
            for offset in range(0, len(lines), capacity):
                chunk = lines[offset:offset + capacity]
                first = chunk[0]
                pages.append(
                    NarrativePage(
                        beat.heading,
                        beat.scene_text,
                        beat.scene_caption,
                        beat.scene_color,
                        tuple(line.content for line in chunk),
                        beat_index,
                        start=(beat_index, first.paragraph, first.offset),
                    )
                )
        if not self._cinematic:
            # Menus, combat readouts, and repeated utility requests should not
            # demand an extra confirmation because their text happened to wrap.
            pages = pages[-1:]
        total = len(pages)
        return tuple(replace(page, number=index + 1, total=total) for index, page in enumerate(pages))

    def advance(self) -> bool:
        if not self.has_next:
            return False
        self.index += 1
        return True

    def previous(self) -> bool:
        if not self.has_previous:
            return False
        self.index -= 1
        return True

    def repaginate(self, *, wrap: WrapText, rows: int) -> tuple[NarrativePage, ...]:
        """Reflow the active prompt while retaining its current reading place."""

        current = self.current
        if current is None:
            return self.pages
        anchor = current.start
        self.pages = self._paginate(wrap, rows)
        # Choose the last page beginning at or before the old source location.
        # This can repeat a few already-read lines but cannot skip unread text.
        candidates = [index for index, page in enumerate(self.pages) if page.start <= anchor]
        self.index = candidates[-1] if candidates else 0
        return self.pages

    def discard_pending(self) -> None:
        """Drop separately rendered utility output while retaining story pages."""

        self._pending_beats.clear()
        self._paragraphs.clear()
        self._new_art = False
        if self.current is not None:
            self.heading = self.current.heading
            self.scene_text = self.current.scene_text
            self.scene_caption = self.current.scene_caption
            self.scene_color = self.current.scene_color
