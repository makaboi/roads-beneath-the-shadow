"""Record the actual exploration renderer without changing story or save state.

Run with the development environment:
    python scripts/capture_pixel_demo.py

The eight-second GIF is a crop of the real PixelWindow.  All movement follows
normal click events and collision paths.  The scene engine stays blocked at
its original decision while an optional environmental inspection is opened.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roads_beneath_shadow.app import Game  # noqa: E402
from roads_beneath_shadow.content import ORIGINS  # noqa: E402
from roads_beneath_shadow.models import Character, GameState  # noqa: E402
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow  # noqa: E402
from roads_beneath_shadow.savegame import SaveManager  # noqa: E402
from roads_beneath_shadow.ui import InputClosed  # noqa: E402


def capture(output: Path, *, fps: int = 12) -> tuple[int, tuple[int, int]]:
    if not 8 <= fps <= 20:
        raise ValueError("Use 8 to 20 frames per second for this compact demo.")
    frames: list[Image.Image] = []
    with tempfile.TemporaryDirectory(prefix="roads-pixel-demo-") as temporary:
        ui = PixelUI(fast=False, text_speed="instant", sound=False)
        window = PixelWindow(ui, size=(1200, 900))
        pg = window.pg
        game = Game(ui, saves=SaveManager(Path(temporary) / "saves"))
        game.state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="bree_exploration")
        ui.state_provider = lambda: game.state
        errors: list[Exception] = []

        def story_worker() -> None:
            try:
                game._bree_exploration()
            except InputClosed:
                pass
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=story_worker, name="roads-demo-story", daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                window.drain()
                window.render()
                if window.world.active:
                    break
                if window.reading:
                    window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_RETURN, unicode="\r", mod=0))
                if errors:
                    raise RuntimeError("Demo story could not start") from errors[0]
                time.sleep(0.002)
            else:
                raise RuntimeError("Bree did not reach its exploration decision")

            request = window.request
            state_before = game.state.to_dict()
            spawn = window.world.player_position
            spec = window.world.spec
            tobin = next(point for point in spec.points if point.key == "stable_yard")
            sign = next(look for look in spec.looks if look.key == "pony_sign")

            def click(position: tuple[float, float]) -> None:
                rect = window.world._rect
                screen_position = (rect.left + round(position[0] * rect.width / 320), rect.top + round(position[1] * rect.height / 240))
                window.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=screen_position))

            def interact() -> None:
                window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_e, unicode="e", mod=0))

            for index in range(fps * 8):
                if index == round(fps * 0.75):
                    click(tobin.position)
                elif index == fps * 2:
                    click(sign.position)
                elif index == round(fps * 4.25):
                    interact()
                    if window.world._inspected_look is not sign:
                        raise RuntimeError("The traveler did not reach the optional inspection")
                elif index == round(fps * 5.75):
                    interact()
                    click(spawn)
                # Advance the real controller by one movie frame. Rendering
                # adds no elapsed time because frames are encoded off line.
                window.world.update(1 / fps)
                window._frame_tick = pg.time.get_ticks()
                window.render()
                if window.request is not request or not worker.is_alive() or errors:
                    raise RuntimeError("Recording unexpectedly answered a story choice")
                picture = window.screen.subsurface(window.world._rect)
                frames.append(Image.frombytes("RGB", picture.get_size(), pg.image.tobytes(picture, "RGB")))

            if game.state.to_dict() != state_before:
                raise RuntimeError("Recording unexpectedly changed the journey state")
            if not ui.responses.empty():
                raise RuntimeError("Recording queued an engine answer")
            if any(abs(a - b) > 0.1 for a, b in zip(window.world.player_position, spawn)):
                raise RuntimeError("The traveler did not return to the loop's starting position")
        finally:
            ui.close()
            worker.join(timeout=1)
            pg.quit()
            if worker.is_alive():
                raise RuntimeError("The recording's story worker did not close")

    # One shared GIF palette avoids color flicker. No dithering introduces
    # extra pixels into the actual nearest-neighbor game screenshots.
    palette_source = Image.new("RGB", (frames[0].width, frames[0].height * 4))
    for row, index in enumerate((0, fps * 2, round(fps * 4.5), fps * 7)):
        palette_source.paste(frames[index], (0, row * frames[0].height))
    palette = palette_source.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    durations = [round((index + 1) * 100 / fps) * 10 - round(index * 100 / fps) * 10 for index in range(len(encoded))]
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(output, save_all=True, append_images=encoded[1:], duration=durations, loop=0, optimize=True, disposal=1)
    return len(frames), frames[0].size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "pixel-exploration.gif")
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    count, size = capture(args.output, fps=args.fps)
    print(f"Captured {count} actual game frames at {size[0]}x{size[1]}: {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
