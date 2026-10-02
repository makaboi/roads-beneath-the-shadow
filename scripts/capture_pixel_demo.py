"""Record the actual exploration renderer without changing story or save state.

Run with the development environment:
    python scripts/capture_pixel_demo.py
    python scripts/capture_pixel_demo.py --montage

The eight-second GIF is a crop of the real PixelWindow.  All movement follows
normal click events and collision paths.  The scene engine stays blocked at
its original decision while an optional environmental inspection is opened.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roads_beneath_shadow.app import Game  # noqa: E402
from roads_beneath_shadow.content import ORIGINS  # noqa: E402
from roads_beneath_shadow.models import Character, GameState  # noqa: E402
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow  # noqa: E402
from roads_beneath_shadow.profile import ProfileManager  # noqa: E402
from roads_beneath_shadow.savegame import SaveManager  # noqa: E402
from roads_beneath_shadow.settings import SettingsManager  # noqa: E402
from roads_beneath_shadow.ui import InputClosed  # noqa: E402


def capture(output: Path, *, fps: int = 12) -> tuple[int, tuple[int, int]]:
    if not 8 <= fps <= 20:
        raise ValueError("Use 8 to 20 frames per second for this compact demo.")
    frames: list[Image.Image] = []
    with tempfile.TemporaryDirectory(prefix="roads-pixel-demo-") as temporary:
        ui = PixelUI(fast=False, text_speed="instant", sound=False)
        window = PixelWindow(ui, size=(1200, 900))
        pg = window.pg
        isolated = Path(temporary)
        game = Game(ui, saves=SaveManager(isolated / "saves"), profile=ProfileManager(isolated / "profile.json"), settings_manager=SettingsManager(isolated / "settings.json"))
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


MONTAGE_SCENES = (
    ("pony", "chapter1_decision", "_chapter_one_decision", {}),
    ("bree", "bree_exploration", "_bree_exploration", {}),
    ("north-gate", "north_gate", "_north_gate", {"north_gate_truth_chosen": True}),
    ("road-fork", "road_from_bree", "_road_from_bree", {}),
    ("camp", "midgewater_camp", "_midgewater_camp", {"midgewater_topic_chosen": True}),
    ("watch-post", "missing_watchman", "_missing_watchman", {}),
    ("wayhouse", "wayhouse", "_wayhouse", {"wayhouse_opened": True}),
    ("hall", "part2_hall_exploration", None, {}),
    ("bridge", "part2_echo_bridge", None, {"part_two_hidden_route_known": True}),
    ("drowned-mile", "part2_drowned_mile", None, {}),
    ("sluice", "part2_prisoners", None, {}),
    ("refuge", "part2_house_under_ash", None, {}),
    ("lantern", "part2_vigil", None, {}),
)


def capture_montage(output: Path, *, fps: int = 12, maps: tuple[str, ...] | None = None) -> tuple[int, tuple[int, int]]:
    """Record thirteen actual maps at 60 fps, with three origin silhouettes.

    ``maps`` restricts a development smoke run to named maps. The normal
    montage includes every scene. A companion JSON file records capture
    boundaries and state checks; GIF encoding may merge identical frames.
    """
    if not 8 <= fps <= 20:
        raise ValueError("Use 8 to 20 frames per second for this compact demo.")
    known_maps = {scene[0] for scene in MONTAGE_SCENES}
    if maps is not None and (not maps or set(maps) - known_maps):
        raise ValueError("Choose one or more known exploration map keys.")
    scenes = tuple(scene for scene in MONTAGE_SCENES if maps is None or scene[0] in maps)
    frames: list[Image.Image] = []
    shots: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="roads-pixel-montage-") as temporary:
        isolated = Path(temporary)
        ui = PixelUI(fast=False, text_speed="instant", sound=False)
        window = PixelWindow(ui, size=(1200, 900))
        pg = window.pg
        game = Game(ui, saves=SaveManager(isolated / "saves"), profile=ProfileManager(isolated / "profile.json"), settings_manager=SettingsManager(isolated / "settings.json"))
        ui.state_provider = lambda: game.state
        worker = None
        try:
            for index, (map_key, scene, method, flags) in enumerate(scenes):
                state = GameState(Character.from_origin("Mira", ORIGINS[index % len(ORIGINS)]), scene=scene, chapter=1 if method else 2, journey_id=f"montage-{index}", flags={"part_two_mara_present": True, "part_two_tobin_present": True, **flags})
                # The authored checkpoint includes the Last Lantern's
                # conditional recovery choice and Calenor's recovered key.
                state.character.hp -= 1
                state.character.add_item("star_key")
                game.state = state
                errors: list[Exception] = []

                def story_worker() -> None:
                    try:
                        if method:
                            getattr(game, method)()
                        else:
                            game.part_two.run_scene(state)
                    except InputClosed:
                        pass
                    except Exception as error:
                        errors.append(error)

                worker = threading.Thread(target=story_worker, name="roads-montage-story", daemon=True)
                worker.start()
                setup_choices = []

                def tick() -> None:
                    for event in pg.event.get():
                        if event.type != pg.QUIT:
                            window.handle_event(event)
                    window.drain()
                    window.render()
                    pg.display.flip()
                    window.clock.tick(60)
                    if errors or window.error:
                        raise RuntimeError(f"Could not record {map_key}: {errors or window.error}")

                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    tick()
                    if window.reading:
                        window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_RETURN, unicode="\r", mod=0))
                    elif window.world.active and window.world.map_key == map_key:
                        break
                    elif (
                        map_key == "refuge" and not setup_choices
                        and window.request and window.request.story
                        and window.request.label == "MARA TOUCHES THE COLD SHACKLE"
                        and window.request.options == ("Share the forge truth with Mara", "Keep moving")
                    ):
                        # This known prelude keeps its truth choice local
                        # until the later route is answered. Use the normal
                        # input handler; no route or reward is submitted.
                        setup_choices.append({"heading": window.request.label, "answer": 1, "option": window.request.options[0]})
                        window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_1, unicode="1", mod=0))
                    elif window.request and window.request.story:
                        raise RuntimeError(f"Unexpected decision before {map_key}: {window.request.label}")
                else:
                    raise RuntimeError(f"The story did not enter {map_key}")

                world = window.world
                request = window.request
                state_before = state.to_dict()

                def validate() -> None:
                    if window.request is not request or not worker.is_alive() or state.to_dict() != state_before or not ui.responses.empty():
                        raise RuntimeError(f"Recording {map_key} unexpectedly answered a story choice")
                    if not world._position_clear(world.player_position) or any(not world._position_clear(position) for position in world.party_positions.values()):
                        raise RuntimeError(f"An actor left the walkable area in {map_key}")

                # Let the checkpoint notice expire through the real renderer.
                deadline = time.monotonic() + 4.1
                while time.monotonic() < deadline:
                    tick()
                    validate()
                first_frame = len(frames)
                started = time.monotonic()
                next_sample = started
                duration = 1.8
                target = world.points[0].point.position
                look = None
                if map_key == "bridge":
                    target = (152, 120)
                elif map_key == "lantern":
                    look = next(item for item in world.spec.looks if item.key == "ordinary_lantern")
                    target = (look.position[0], look.position[1] - 10)
                    duration = 4.5
                rect = world._rect
                position = (rect.left + round(target[0] * rect.width / 320), rect.top + round(target[1] * rect.height / 240))
                window.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=position))
                inspected = False
                while time.monotonic() - started < duration:
                    tick()
                    now = time.monotonic()
                    if look and not world._path and not inspected:
                        window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_e, unicode="e", mod=0))
                        inspected = True
                        if not world.inspection_open:
                            raise RuntimeError("The traveler did not reach the optional inspection")
                    if now >= next_sample:
                        picture = window.screen.subsurface(world._rect)
                        frame = Image.frombytes("RGB", picture.get_size(), pg.image.tobytes(picture, "RGB"))
                        # Keep each native pixel exact when the movie is
                        # enlarged; palette encoding introduces no dithering.
                        frames.append(frame.resize((320, 240), Image.Resampling.NEAREST))
                        next_sample += 1 / fps
                    validate()
                shots.append({"map": map_key, "scene": scene, "origin": state.character.origin, "captured_start_frame": first_frame, "captured_frames": len(frames) - first_frame, "setup_choices": setup_choices, "inspection": inspected, "story_state_unchanged": True, "party": list(world.party_positions), "world_rect": tuple(world._rect)})
                print(f"Captured {map_key}: {len(frames) - first_frame} actual frames", flush=True)
                # Cancel only after the captured clip; no paid story choice.
                window.answer(None)
                worker.join(timeout=2)
                if worker.is_alive():
                    raise RuntimeError(f"The {map_key} story worker did not close")
        finally:
            ui.close()
            if worker is not None:
                worker.join(timeout=2)
            pg.quit()
            if worker is not None and worker.is_alive():
                raise RuntimeError("The montage's story worker did not close")

    palette_source = Image.new("RGB", (320, 240 * (len(shots) + 1)))
    for row, shot in enumerate(shots):
        palette_source.paste(frames[shot["captured_start_frame"]], (0, row * 240))
    palette_source.paste(frames[-1], (0, len(shots) * 240))
    palette = palette_source.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    encoded = [frame.resize((640, 480), Image.Resampling.NEAREST).quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    durations = [round((index + 1) * 100 / fps) * 10 - round(index * 100 / fps) * 10 for index in range(len(encoded))]
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(output, save_all=True, append_images=encoded[1:], duration=durations, loop=0, optimize=True, disposal=1)
    with Image.open(output) as gif:
        encoded_frames = gif.n_frames
        duration_ms = sum(frame.info.get("duration", 0) for frame in ImageSequence.Iterator(gif))
    for shot in shots:
        shot["start_ms"] = round(shot["captured_start_frame"] * 100 / fps) * 10
        shot["end_ms"] = round((shot["captured_start_frame"] + shot["captured_frames"]) * 100 / fps) * 10
    report = {"output": str(output), "captured_frames": len(frames), "encoded_frames": encoded_frames, "duration_ms": duration_ms, "size": (640, 480), "fps": fps, "bytes": output.stat().st_size, "shots": shots, "source": "Actual PixelWindow, real story workers and normal SDL input/collision; every captured story state remained unchanged."}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    return len(frames), (640, 480)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--montage", action="store_true", help="Record all thirteen real exploration scenes and three origins.")
    args = parser.parse_args()
    output = args.output or ROOT / "assets" / ("pixel-exploration-montage.gif" if args.montage else "pixel-exploration.gif")
    count, size = (capture_montage if args.montage else capture)(output, fps=args.fps)
    print(f"Captured {count} actual game frames at {size[0]}x{size[1]}: {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
