"""Measured, offline Unicode fallbacks without owning SDL or changing text.

Only immutable cmap data may be shared between windows. Font handles and
layout caches belong to each adapter and disappear with that adapter.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping
from unicodedata import category, name


COVERAGE_FILE = "fallback-coverage.json"
FALLBACK_LICENSE = "FALLBACK-OFL.txt"
FONT_NAMES = {
    "regular": "DejaVuSansMono.ttf",
    "bold": "DejaVuSansMono-Bold.ttf",
    "cjk": "RBSRoadCJK-Regular.otf",
    "devanagari": "NotoSansDevanagari-Regular.ttf",
}
FALLBACK_FILES = (FONT_NAMES["cjk"], FONT_NAMES["devanagari"], COVERAGE_FILE, FALLBACK_LICENSE)
LAYOUT_CACHE_LIMIT = 256
FONT_CACHE_LIMIT = 12
MAX_CACHED_TEXT = 512
MAX_COVERAGE_BYTES = 131072


def _variation_selector(character: str) -> bool:
    point = ord(character)
    return 0xFE00 <= point <= 0xFE0F or 0xE0100 <= point <= 0xE01EF


def _hangul_kind(character: str) -> str | None:
    point = ord(character)
    if 0x1100 <= point <= 0x115F or 0xA960 <= point <= 0xA97C:
        return "L"
    if 0x1160 <= point <= 0x11A7 or 0xD7B0 <= point <= 0xD7C6:
        return "V"
    if 0x11A8 <= point <= 0x11FF or 0xD7CB <= point <= 0xD7FB:
        return "T"
    if 0xAC00 <= point <= 0xD7A3:
        return "LV" if (point - 0xAC00) % 28 == 0 else "LVT"
    return None


def text_clusters(text: str) -> Iterator[str]:
    """Keep marks, variation selectors and conjunct continuations together.

    This is sufficient for the bundled scripts and common combining accents;
    it is not a replacement for a complete Unicode grapheme/bidi editor.
    """
    cluster = ""
    continuation = False
    for character in text:
        joined = category(character).startswith("M") or _variation_selector(character) or character in "\u200c\u200d"
        if cluster:
            previous_hangul, current_hangul = _hangul_kind(cluster[-1]), _hangul_kind(character)
            joined = joined or (previous_hangul == "L" and current_hangul in {"L", "V", "LV", "LVT"} or
                               previous_hangul in {"LV", "V"} and current_hangul in {"V", "T"} or
                               previous_hangul in {"LVT", "T"} and current_hangul == "T")
        if cluster and not joined and not continuation:
            yield cluster
            cluster = ""
        cluster += character
        continuation = character == "\u200d" or "VIRAMA" in name(character, "") or "HALANT" in name(character, "")
    if cluster:
        yield cluster


def caret_positions(font: Any, text: str) -> tuple[int, ...]:
    """Bound source-offset advances when shaping a prefix changes its width.

    Source offsets remain unchanged. Positions inside a shaped conjunct may
    coincide; this prevents backwards carets and negative selection widths.
    """
    total = max(0, font.size(text)[0])
    positions = [0]
    for offset in range(1, len(text) + 1):
        positions.append(max(positions[-1], min(total, max(0, font.size(text[:offset])[0]))))
    return tuple(positions)


def text_viewport(font: Any, text: str, width: int, caret: int, *,
                  preferred_start: int = 0, prefix_width: int = 0,
                  caret_padding: int = 0) -> tuple[int, int]:
    """Choose a source-preserving slice without cutting a shaped cluster."""
    if not text:
        return 0, 0
    boundaries = [0]
    for cluster in text_clusters(text):
        boundaries.append(boundaries[-1] + len(cluster))
    caret = max(0, min(len(text), int(caret)))
    preferred = max(0, min(caret, int(preferred_start)))
    start_index = bisect_right(boundaries, preferred) - 1
    # An end-of-line caret still shows the final whole cluster.
    start_index = min(start_index, len(boundaries) - 2)
    maximum_start = min(bisect_right(boundaries, caret) - 1, len(boundaries) - 2)
    required_end = boundaries[bisect_left(boundaries, caret)]
    width, prefix_width, caret_padding = max(0, int(width)), max(0, int(prefix_width)), max(0, int(caret_padding))

    def available(start: int) -> int:
        return max(0, width - (prefix_width if start else 0))

    while start_index < maximum_start:
        start = boundaries[start_index]
        if font.size(text[start:caret])[0] + caret_padding <= available(start):
            break
        start_index += 1
    start = boundaries[start_index]
    end = boundaries[start_index + 1]
    for boundary in boundaries[start_index + 1:]:
        if font.size(text[start:boundary])[0] <= available(start):
            end = boundary
    return start, max(end, required_end)


@dataclass(frozen=True)
class _Ranges:
    ranges: tuple[tuple[int, int], ...]
    starts: tuple[int, ...]
    count: int
    sha256: str

    def contains(self, character: str) -> bool:
        point = ord(character)
        index = bisect_right(self.starts, point) - 1
        return index >= 0 and point <= self.ranges[index][1]


def _read_coverage(directory: Path) -> Mapping[str, _Ranges]:
    try:
        with (directory / COVERAGE_FILE).open("rb") as source:
            raw = source.read(MAX_COVERAGE_BYTES + 1)
        if len(raw) > MAX_COVERAGE_BYTES:
            raise ValueError("coverage index is too large")
        data = json.loads(raw)
        if type(data.get("schema")) is not int or data["schema"] != 1 or set(data.get("fonts", {})) != set(FONT_NAMES):
            raise ValueError("unknown coverage schema or fonts")
        result = {}
        for kind, filename in FONT_NAMES.items():
            entry = data["fonts"][kind]
            if entry.get("filename") != filename:
                raise ValueError("coverage filenames must be bundled package filenames")
            digest = entry.get("sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid font checksum")
            rows = entry.get("ranges")
            if not isinstance(rows, list) or not 0 < len(rows) <= 5000:
                raise ValueError("invalid coverage ranges")
            ranges = []
            previous = -1
            for row in rows:
                if (not isinstance(row, list) or len(row) != 2 or
                        any(not isinstance(n, int) or isinstance(n, bool) for n in row)):
                    raise ValueError("invalid coverage range")
                start, end = row
                if not 0 <= start <= end <= 0x10FFFF or start <= previous:
                    raise ValueError("overlapping or invalid coverage range")
                ranges.append((start, end))
                previous = end
            count = sum(end - start + 1 for start, end in ranges)
            if type(entry.get("codepoints")) is not int or entry["codepoints"] != count:
                raise ValueError("coverage count does not match ranges")
            result[kind] = _Ranges(tuple(ranges), tuple(start for start, _ in ranges), count, digest)
        return MappingProxyType(result)
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        raise ValueError(f"{COVERAGE_FILE}: {error}") from error


@lru_cache(maxsize=4)
def _load_coverage(directory: str) -> Mapping[str, _Ranges] | None:
    try:
        return _read_coverage(Path(directory))
    except ValueError:
        return None


def validate_fallback_assets(font_directory: Path) -> dict[str, Any]:
    """Strict, SDL-free package validation used by native diagnostics."""
    directory = Path(font_directory)
    coverage = _read_coverage(directory)
    for kind, filename in FONT_NAMES.items():
        digest = hashlib.sha256()
        try:
            with (directory / filename).open("rb") as source:
                for chunk in iter(lambda: source.read(65536), b""):
                    digest.update(chunk)
        except OSError as error:
            raise ValueError(f"{filename}: {error}") from error
        if digest.hexdigest() != coverage[kind].sha256:
            raise ValueError(f"{filename}: checksum does not match bundled coverage")
    try:
        license_text = (directory / FALLBACK_LICENSE).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{FALLBACK_LICENSE}: {error}") from error
    if "SIL OPEN FONT LICENSE Version 1.1" not in license_text:
        raise ValueError(f"{FALLBACK_LICENSE}: missing OFL license")
    return {"schema": 1, "fonts": {FONT_NAMES[kind]: {"codepoints": value.count, "sha256": value.sha256}
                                  for kind, value in coverage.items()}}


@dataclass(frozen=True)
class _Run:
    kind: str
    text: str
    point_size: int
    x: int
    y: int


@dataclass(frozen=True)
class _Layout:
    width: int
    height: int
    runs: tuple[_Run, ...] | None


class FallbackFont:
    """Preserve the base Font fast path; fit only missing bundled glyph runs."""

    def __init__(self, pg: Any, base_font: Any, point_size: int, *, bold: bool, font_directory: Path):
        self.pg = pg
        self.base = base_font
        self.point_size = point_size
        self.bold_face = bold
        self.directory = Path(font_directory)
        self.base_kind = "bold" if bold else "regular"
        self._fonts: OrderedDict[tuple[str, int], Any] = OrderedDict()
        self._layouts: OrderedDict[str, _Layout] = OrderedDict()
        self._unavailable: set[str] = set()
        self._script: str | None = None
        self._direction: Any = None
        self.shaping_available: bool | None = None
        self._style = self._style_key()

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self.base, attribute)

    def _style_key(self) -> tuple[bool, ...]:
        return tuple(bool(getattr(self.base, getter, lambda: False)())
                     for getter in ("get_bold", "get_italic", "get_underline", "get_strikethrough"))

    def _sync_style(self) -> None:
        style = self._style_key()
        if style != self._style:
            self._style = style
            self._fonts.clear()
            self._layouts.clear()

    def _set_style(self, setter: str, value: bool) -> None:
        getattr(self.base, setter)(value)
        self._sync_style()

    def set_bold(self, value: bool) -> None:
        self._set_style("set_bold", value)

    def set_italic(self, value: bool) -> None:
        self._set_style("set_italic", value)

    def set_underline(self, value: bool) -> None:
        self._set_style("set_underline", value)

    def set_strikethrough(self, value: bool) -> None:
        self._set_style("set_strikethrough", value)

    def set_script(self, value: str) -> None:
        self.base.set_script(value)
        self._script = value
        self._fonts.clear()
        self._layouts.clear()

    def set_direction(self, value: Any) -> None:
        self.base.set_direction(value)
        self._direction = value
        self._fonts.clear()
        self._layouts.clear()

    def _font(self, kind: str, size: int) -> Any:
        physical_kind = "cjk" if kind == "hangul" else kind
        if kind == self.base_kind or physical_kind in self._unavailable:
            return self.base
        key = (kind, size)
        if key not in self._fonts:
            try:
                font = self.pg.font.Font(str(self.directory / FONT_NAMES[physical_kind]), size)
            except (OSError, ValueError, self.pg.error):
                self._unavailable.add(physical_kind)
                return self.base
            font.set_bold(self.bold_face or self._style[0])
            font.set_italic(self._style[1])
            font.set_underline(self._style[2])
            if hasattr(font, "set_strikethrough"):
                font.set_strikethrough(self._style[3])
            script = self._script or {"devanagari": "Deva", "hangul": "Hang"}.get(kind)
            if script is not None:
                try:
                    font.set_script(script)
                    if kind in {"devanagari", "hangul"} and self.shaping_available is not False:
                        self.shaping_available = True
                except (AttributeError, RuntimeError, self.pg.error):
                    if kind in {"devanagari", "hangul"}:
                        self.shaping_available = False
            if self._direction is not None:
                font.set_direction(self._direction)
            self._fonts[key] = font
        self._fonts.move_to_end(key)
        while len(self._fonts) > FONT_CACHE_LIMIT:
            self._fonts.popitem(last=False)
        return self._fonts[key]

    def _kind(self, character: str, previous: str | None, coverage: Mapping[str, _Ranges]) -> str:
        if previous and (_variation_selector(character) or character in "\u200c\u200d"):
            return previous
        previous_coverage = "cjk" if previous == "hangul" else previous
        if previous and category(character).startswith("M") and coverage[previous_coverage].contains(character):
            return previous
        point = ord(character)
        if _hangul_kind(character) and coverage["cjk"].contains(character):
            return "hangul"
        if (0x0900 <= point <= 0x097F or 0xA8E0 <= point <= 0xA8FF) and coverage["devanagari"].contains(character):
            return "devanagari"
        if coverage[self.base_kind].contains(character):
            return self.base_kind
        for kind in ("cjk", "devanagari"):
            if coverage[kind].contains(character):
                return kind
        return self.base_kind

    def _raw_render(self, font: Any, text: str, antialias: bool, color: Any, background: Any = None) -> Any:
        width, height = font.size(text)
        if width == 0:
            return self.pg.Surface((0, max(0, height)), self.pg.SRCALPHA)
        return font.render(text, antialias, color, background)

    def _ink(self, font: Any, text: str) -> Any:
        bounds = self.pg.Rect(0, 0, 0, 0)
        for antialias in (False, True):
            raw = self._raw_render(font, text, antialias, (255, 255, 255))
            alpha = self.pg.Surface(raw.get_size(), self.pg.SRCALPHA)
            alpha.blit(raw, (0, 0))
            ink = alpha.get_bounding_rect()
            if ink.width and ink.height:
                bounds = ink if not bounds.width else bounds.union(ink)
        return bounds

    def _layout(self, text: str) -> _Layout:
        self._sync_style()
        if text.isascii():
            return _Layout(*self.base.size(text), None)
        if text in self._layouts:
            self._layouts.move_to_end(text)
            return self._layouts[text]
        coverage = _load_coverage(str(self.directory))
        if coverage is None:
            return _Layout(*self.base.size(text), None)
        groups: list[list[str]] = []
        previous = None
        for character in text:
            kind = self._kind(character, previous, coverage)
            if groups and kind == groups[-1][0]:
                groups[-1][1] += character
            else:
                groups.append([kind, character])
            previous = kind
        if all(kind == self.base_kind for kind, _ in groups):
            layout = _Layout(*self.base.size(text), None)
        else:
            x = 0
            height = self.base.get_height()
            runs = []
            for kind, value in groups:
                size = self.point_size
                while True:
                    font = self._font(kind, size)
                    ink = self._ink(font, value)
                    if ink.height <= height or kind == self.base_kind or size <= 1:
                        break
                    size -= 1
                y = self.base.get_ascent() - font.get_ascent()
                y = max(-ink.top, min(y, height - ink.bottom)) if ink.height else 0
                runs.append(_Run(kind, value, size, x, y))
                x += font.size(value)[0]
            layout = _Layout(x, height, tuple(runs))
        if len(text) <= MAX_CACHED_TEXT:
            self._layouts[text] = layout
            while len(self._layouts) > LAYOUT_CACHE_LIMIT:
                self._layouts.popitem(last=False)
        return layout

    def size(self, text: str) -> tuple[int, int]:
        layout = self._layout(text)
        return layout.width, layout.height

    def metrics(self, text: str) -> list[Any]:
        """Individual glyph metrics; cmap membership controls availability."""
        coverage = _load_coverage(str(self.directory))
        if text.isascii() or coverage is None or all(coverage[self.base_kind].contains(c) for c in text):
            return self.base.metrics(text)
        result = []
        previous = None
        for character in text:
            kind = self._kind(character, previous, coverage)
            physical_kind = "cjk" if kind == "hangul" else kind
            previous = kind
            if not coverage[physical_kind].contains(character):
                result.append(None)
                continue
            layout = self._layout(character)
            if layout.runs:
                run = layout.runs[0]
                font = self._font(run.kind, run.point_size)
                shift = self.base.get_ascent() - font.get_ascent() - run.y
            else:
                font, shift = self.base, 0
            metric = font.metrics(character)[0]
            if metric is not None and physical_kind not in self._unavailable:
                left, right, bottom, top, advance = metric
                metric = left, right, bottom + shift, top + shift, advance
            else:
                metric = None
            result.append(metric)
        return result

    def render(self, text: str, antialias: bool, color: Any, background: Any = None) -> Any:
        layout = self._layout(text)
        if layout.runs is None:
            return self._raw_render(self.base, text, antialias, color, background)
        surface = self.pg.Surface((layout.width, layout.height), self.pg.SRCALPHA)
        if background is not None:
            surface.fill(background)
        for run in layout.runs:
            raw = self._raw_render(self._font(run.kind, run.point_size), run.text, antialias, color)
            surface.blit(raw, (run.x, run.y))
        return surface
