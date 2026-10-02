"""Terminal rendering, accessible prompts, color, motion, and sound cues."""

from __future__ import annotations

import os
import select
import shutil
import sys
import textwrap
import time
from collections.abc import Callable, Sequence
from numbers import Real
from unicodedata import decimal

from .lighting import ASCII_RAMP, Color, art_ink


TEXT_SPEED_DELAYS: dict[str, float] = {
    "instant": 0.0,
    "fast": 0.035,
    "normal": 0.10,
    "slow": 0.22,
}


class InputClosed(Exception):
    """Raised when the terminal input stream is closed."""


def choice_number(text: str, option_count: int) -> int | None:
    """Read a bounded menu number without converting an unbounded integer.

    Unicode decimal digits share the ordinary numbered-choice behavior.
    Superscripts and other numeric-looking text are unrelated input, and
    oversized pasted numbers must not interrupt the pending choice.
    """

    if option_count < 1 or not text.isdecimal():
        return None
    value = 0
    for character in text:
        value = value * 10 + decimal(character)
        if value > option_count:
            return None
    return value if value >= 1 else None


class TerminalUI:
    """A dependency-free presentation layer for both terminals and test runners.

    ``fast`` remains the master switch used by the existing automated tests.  The
    newer ``text_speed``, ``reduced_motion``, and ``screen_reader`` options are
    independent player preferences and may be changed between scenes.
    """

    def __init__(
        self,
        *,
        color: bool | None = None,
        sound: bool = False,
        fast: bool = False,
        text_speed: str | float = "normal",
        reduced_motion: bool | None = None,
        screen_reader: bool = False,
        keyboard_navigation: bool = True,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        sleep_fn: Callable[[float], None] = time.sleep,
        terminal_size_fn: Callable[..., os.terminal_size] = shutil.get_terminal_size,
        sound_fn: Callable[[str], bool | None] | None = None,
    ) -> None:
        self.color = self._supports_color() if color is None else color
        self.sound_enabled = sound
        self.fast = fast
        self.text_speed = self._validate_text_speed(text_speed)
        if reduced_motion is None:
            reduced_motion = os.environ.get("REDUCED_MOTION", "").lower() in {"1", "true", "yes"}
        self.reduced_motion = bool(reduced_motion)
        self.screen_reader = bool(screen_reader)
        self.keyboard_navigation = bool(keyboard_navigation)
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.sleep_fn = sleep_fn
        self.terminal_size_fn = terminal_size_fn
        self.sound_fn = sound_fn

    @staticmethod
    def _supports_color() -> bool:
        return sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb" and "NO_COLOR" not in os.environ

    @staticmethod
    def _validate_text_speed(value: str | float) -> str | float:
        if isinstance(value, str):
            normalized = value.lower().strip()
            if normalized not in TEXT_SPEED_DELAYS:
                choices = ", ".join(TEXT_SPEED_DELAYS)
                raise ValueError(f"text_speed must be one of {choices}")
            return normalized
        if isinstance(value, Real) and not isinstance(value, bool) and value >= 0:
            return float(value)
        raise ValueError("text_speed must be a named speed or a non-negative delay")

    @property
    def width(self) -> int:
        """Current usable width, clamped only to avoid pathological values."""

        try:
            columns = self.terminal_size_fn((78, 24)).columns
        except (AttributeError, OSError, TypeError):
            columns = 78
        return max(24, min(92, int(columns)))

    @property
    def narration_delay(self) -> float:
        if self.fast:
            return 0.0
        if isinstance(self.text_speed, str):
            return TEXT_SPEED_DELAYS[self.text_speed]
        return self.text_speed

    @property
    def motion_enabled(self) -> bool:
        return not (self.fast or self.reduced_motion or self.screen_reader)

    @property
    def _interactive_terminal(self) -> bool:
        return (
            os.name == "posix"
            and self.input_fn is input
            and self.output_fn is print
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )

    def set_text_speed(self, value: str | float) -> None:
        """Change narration pacing without rebuilding the UI object."""

        self.text_speed = self._validate_text_speed(value)

    def style(self, text: str, *codes: str) -> str:
        if not self.color or self.screen_reader:
            return text
        return "".join(codes) + text + Color.RESET

    def clear(self) -> None:
        if self.fast:
            return
        if self.screen_reader or self.reduced_motion:
            self.write()
        elif sys.stdout.isatty():
            self.output_fn("\033[2J\033[H")

    def write(self, text: str = "", *, color: str | None = None, bold: bool = False) -> None:
        codes: list[str] = []
        if color:
            codes.append(color)
        if bold:
            codes.append(Color.BOLD)
        # Below 50 columns, wrap even direct status/quote writes so the host
        # terminal never has to split words at arbitrary screen boundaries.
        if self.width < 50 and any(len(line) > self.width for line in text.splitlines()):
            source_lines = text.splitlines() or [""]
            for source_line in source_lines:
                wrapped = textwrap.wrap(
                    source_line,
                    width=self.width,
                    break_long_words=False,
                    break_on_hyphens=False,
                ) or [""]
                for line in wrapped:
                    self.output_fn(self.style(line, *codes))
            return
        self.output_fn(self.style(text, *codes))

    def rule(self, char: str = "=") -> None:
        if self.screen_reader:
            self.write()
            return
        glyph = char[0] if char else "="
        self.write(glyph * min(72, self.width), color=Color.DIM)

    def title(self, text: str) -> None:
        if self.screen_reader:
            self.write(text)
            return
        stage_width = min(72, self.width)
        self.rule()
        self.write(text.center(stage_width), color=Color.YELLOW, bold=True)
        self.rule()

    @staticmethod
    def _art_lines(text: str) -> list[str]:
        cleaned = textwrap.dedent(text).strip("\n")
        return cleaned.splitlines() if cleaned else []

    def _art_line(self, line: str, color: str) -> str:
        """Light converter marks after layout, without counting ANSI as width."""

        if not self.color:
            return line
        if any(character not in ASCII_RAMP for character in line):
            return self.style(line, color)
        rendered: list[str] = []
        previous_ink = None
        for character in line:
            ink = art_ink(character, color)
            if character != " ":
                code = f"\033[38;5;{ink}m" if ink is not None else color
                if code != previous_ink:
                    rendered.append(code)
                    previous_ink = code
            rendered.append(character)
        if previous_ink is not None:
            rendered.append(Color.RESET)
        return "".join(rendered)

    def art(
        self,
        text: str,
        color: str = Color.SILVER,
        *,
        alt_text: str | None = None,
    ) -> None:
        """Render centered art without allowing a wide piece to hard-wrap.

        In screen-reader mode decorative art is omitted.  Callers may supply a
        short ``alt_text`` for a story-relevant illustration.
        """

        animation_frames = getattr(text, "frames", None)
        if animation_frames:
            self.animate(
                animation_frames,
                color,
                alt_text=alt_text,
                frame_offsets=getattr(text, "frame_offsets", None),
            )
            return

        if self.screen_reader:
            if alt_text:
                self.write(f"[Scene: {alt_text}]", color=color)
            return

        lines = self._art_lines(text)
        if not lines:
            return
        stage_width = self.width
        block_width = max(len(line) for line in lines)
        if block_width <= stage_width:
            indent = " " * ((stage_width - block_width) // 2)
            for line in lines:
                self.output_fn(self._art_line(indent + line.rstrip(), color))
            return

        # Very narrow terminals get a centered viewport rather than terminal
        # wrapping, which would destroy silhouettes and architectural lines.
        left = (block_width - stage_width) // 2
        for line in lines:
            viewport = line.ljust(block_width)[left : left + stage_width].rstrip()
            self.output_fn(self._art_line(viewport, color))

    def animate(
        self,
        frames: Sequence[str],
        color: str = Color.SILVER,
        *,
        frame_delay: float = 0.14,
        repeat: int = 1,
        alt_text: str | None = None,
        frame_offsets: Sequence[int] | None = None,
    ) -> None:
        """Play a restrained sequence of ASCII frames.

        Animation collapses to the final frame in reduced-motion, screen-reader,
        fast, redirected-output, and automated-test environments.
        """

        offsets = (0,) * len(frames) if frame_offsets is None else tuple(frame_offsets)
        if len(offsets) != len(frames) or any(type(offset) is not int or offset < 0 for offset in offsets):
            raise ValueError("frame offsets must provide one non-negative row count per frame")
        available = tuple((frame, offset) for frame, offset in zip(frames, offsets) if frame.strip())
        if not available:
            return
        if not self.motion_enabled or not self._interactive_terminal or len(available) == 1:
            self.art(available[-1][0], color, alt_text=alt_text)
            return

        repeat = max(1, int(repeat))
        delay = max(0.0, float(frame_delay))
        first = True
        for _ in range(repeat):
            for frame, offset in available:
                if not first:
                    self.clear()
                for _row in range(offset):
                    self.write()
                self.art(frame, color, alt_text=alt_text)
                self.sleep_fn(delay)
                first = False

    def narrate(self, text: str, *, color: str | None = None) -> None:
        paragraphs = text.strip().split("\n")
        wrap_width = max(20, min(78, self.width))
        for paragraph in paragraphs:
            if not paragraph.strip():
                self.write()
                continue
            for line in textwrap.wrap(paragraph, width=wrap_width):
                self.write(line, color=color)
            if self.narration_delay:
                self.sleep_fn(self.narration_delay)

    def prompt(self, label: str = "> ") -> str:
        try:
            return self.input_fn(self.style(label, Color.CYAN, Color.BOLD)).strip()
        except EOFError:
            raise InputClosed from None

    def _choice_lines(
        self,
        title: str,
        options: Sequence[str],
        selected: int,
        allow_back: bool,
        *,
        raw_keys: bool,
    ) -> list[tuple[str, str | None, bool]]:
        lines: list[tuple[str, str | None, bool]] = [(title, Color.YELLOW, True)]
        option_width = max(12, self.width - 7)
        for index, option in enumerate(options, 1):
            wrapped = textwrap.wrap(str(option), width=option_width) or [""]
            if self.screen_reader:
                prefix = f"{index}. "
                option_color = None
                bold = False
            else:
                marker = ">" if index - 1 == selected else " "
                prefix = f"{marker} [{index}] "
                option_color = Color.CYAN if index - 1 == selected else None
                bold = index - 1 == selected
            lines.append((prefix + wrapped[0], option_color, bold))
            continuation = " " * len(prefix)
            lines.extend((continuation + part, option_color, bold) for part in wrapped[1:])
        if allow_back:
            label = "B. Back" if self.screen_reader else "  [B] Back"
            lines.append((label, Color.DIM, False))
        if self.keyboard_navigation and not self.screen_reader:
            hint = "[W/S or arrows] Move  [Return/D] Select"
            if allow_back:
                hint += "  [A/B] Back"
            lines.append((hint, Color.DIM, False))
        if raw_keys:
            lines.append((f"Choose: [{selected + 1}]", Color.CYAN, True))
        return lines

    def _render_choice_lines(self, lines: Sequence[tuple[str, str | None, bool]]) -> None:
        for line, color, bold in lines:
            self.write(line, color=color, bold=bold)

    @staticmethod
    def _read_raw_key() -> str:
        """Read one terminal key, including a complete ANSI arrow sequence."""

        try:
            import termios
            import tty
        except ImportError:
            return ""

        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            first = sys.stdin.read(1)
            if first != "\x1b":
                return first
            suffix = ""
            while len(suffix) < 2 and select.select([sys.stdin], [], [], 0.025)[0]:
                suffix += sys.stdin.read(1)
            return first + suffix
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)

    def _rewrite_choice_lines(self, previous_count: int, lines: Sequence[tuple[str, str | None, bool]]) -> None:
        sys.stdout.write(f"\033[{previous_count}A")
        sys.stdout.flush()
        for line, color, bold in lines:
            sys.stdout.write("\033[2K")
            codes = ([color] if color else []) + ([Color.BOLD] if bold else [])
            sys.stdout.write(self.style(line, *codes) + "\n")
        sys.stdout.flush()

    def _choose_with_raw_keys(self, title: str, options: Sequence[str], allow_back: bool) -> int | None:
        selected = 0
        lines = self._choice_lines(title, options, selected, allow_back, raw_keys=True)
        self._render_choice_lines(lines)
        while True:
            key = self._read_raw_key()
            if key in {"", "\x04"}:
                raise InputClosed
            if key == "\x03":
                raise KeyboardInterrupt
            normalized = key.lower()
            if normalized in {"w", "k", "\x1b[a"}:
                selected = (selected - 1) % len(options)
            elif normalized in {"s", "j", "\x1b[b"}:
                selected = (selected + 1) % len(options)
            elif normalized in {"\r", "\n", "d", "l", "\x1b[c"}:
                return selected + 1
            elif allow_back and normalized in {"a", "h", "b", "q", "\x1b[d", "\x1b"}:
                return None
            elif (number := choice_number(normalized, len(options))) is not None:
                return number
            else:
                continue
            updated = self._choice_lines(title, options, selected, allow_back, raw_keys=True)
            self._rewrite_choice_lines(len(lines), updated)
            lines = updated

    def choose(self, title: str, options: Sequence[str], *, allow_back: bool = False) -> int | None:
        if not options:
            raise ValueError("choose requires at least one option")
        if (
            self.keyboard_navigation
            and not self.screen_reader
            and self._interactive_terminal
            and len(options) <= 9
        ):
            self.write()
            return self._choose_with_raw_keys(title, options, allow_back)

        selected = 0
        while True:
            self.write()
            lines = self._choice_lines(title, options, selected, allow_back, raw_keys=False)
            self._render_choice_lines(lines)
            answer = self.prompt("Enter your choice: ").lower()
            if allow_back and answer in {"b", "back", "q", "a", "h", "\x1b[d"}:
                return None
            if (number := choice_number(answer, len(options))) is not None:
                return number
            if self.keyboard_navigation:
                if answer in {"w", "k", "up", "\x1b[a"}:
                    selected = (selected - 1) % len(options)
                    continue
                if answer in {"s", "j", "down", "\x1b[b"}:
                    selected = (selected + 1) % len(options)
                    continue
                if answer in {"", "d", "l", "right", "\x1b[c"}:
                    return selected + 1
            self.write("Choose one of the listed options.", color=Color.RED)

    def pause(self, message: str = "Press Return to continue...") -> None:
        if not self.fast:
            self.prompt(message)

    def sound(self, cue: str = "notice") -> None:
        if not self.sound_enabled:
            return
        if self.sound_fn is not None:
            try:
                handled = self.sound_fn(cue)
            except (OSError, RuntimeError):
                handled = False
            if handled is not False:
                return
        patterns = {"danger": 2, "victory": 3, "notice": 1}
        self.output_fn("\a" * patterns.get(cue, 1))

    def meter(self, label: str, value: int, maximum: int, *, color: str = Color.GREEN) -> str:
        maximum = max(1, maximum)
        if self.screen_reader:
            return f"{label}: {value} of {maximum}"
        bar_width = max(8, min(16, self.width - 20))
        filled = max(0, min(bar_width, round((value / maximum) * bar_width)))
        bar = "#" * filled + "-" * (bar_width - filled)
        return self.style(f"{label:<7} [{bar}] {value}/{maximum}", color)
