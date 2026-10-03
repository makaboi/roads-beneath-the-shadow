"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .app import Game
from .audio import SoundPlayer
from .profile import ProfileManager
from .settings import SettingsManager
from .ui import InputClosed, TerminalUI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play The Lord of the Rings: Roads Beneath the Shadow")
    parser.add_argument("--version", action="version", version=f"Roads Beneath the Shadow {__version__}")
    presentation = parser.add_mutually_exclusive_group()
    presentation.add_argument("--pixel", action="store_true", help="open the pixel-art desktop game (default)")
    presentation.add_argument("--terminal", action="store_true", help="play the original dependency-free terminal edition")
    parser.add_argument("--screenshot", type=Path, help="render the pixel-art main menu to a PNG and exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI terminal colors")
    parser.add_argument("--sound", action="store_true", help="enable sound cues and pixel-edition ambient music")
    parser.add_argument("--fast", action="store_true", help="remove dramatic pauses (useful for testing)")
    parser.add_argument(
        "--text-speed",
        choices=("slow", "normal", "fast", "instant"),
        help="override the saved narration speed for this launch",
    )
    parser.add_argument("--reduced-motion", action="store_true", help="disable scene animation")
    parser.add_argument(
        "--screen-reader",
        action="store_true",
        help="replace decorative art with concise scene descriptions",
    )
    parser.add_argument(
        "--difficulty",
        choices=("story", "ranger", "shadow"),
        help="choose story, intended Ranger, or hard Shadow combat",
    )
    parser.add_argument("--check-install", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check-runtime-assets", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.screenshot and (args.terminal or args.screen_reader):
        parser.error("--screenshot requires pixel-art mode")
    if args.check_runtime_assets:
        from .runtime_assets import verify_runtime_assets

        print(json.dumps(verify_runtime_assets(), sort_keys=True))
        return
    if args.check_install:
        missing = SoundPlayer.missing_cues()
        if missing:
            raise SystemExit(f"Installation check failed; missing sound cues: {', '.join(missing)}")
        from .pixel_art import missing_assets

        missing_pixel_scenes = missing_assets()
        if missing_pixel_scenes:
            raise SystemExit(
                "Installation check failed; pixel-art scenes are missing: "
                + ", ".join(path.name for path in missing_pixel_scenes)
            )
        from .pixel_world import missing_world_assets
        from .pixel_theme import missing_font_assets
        from .soundscapes import AUDIO_DIRECTORY, TRACKS

        missing_exploration = missing_world_assets()
        missing_ambient = [AUDIO_DIRECTORY / filename for filename in TRACKS.values() if not (AUDIO_DIRECTORY / filename).is_file()]
        missing_new = missing_exploration + missing_ambient + missing_font_assets()
        if missing_new:
            raise SystemExit("Installation check failed; missing exploration, ambient, or font assets: " + ", ".join(path.name for path in missing_new))
        print(f"Installation verified: {len(SoundPlayer.CUES)} sound cues, pixel-art scenes, exploration maps, and ambient tracks are available.")
        return
    settings_manager = SettingsManager()
    settings = settings_manager.load()
    if args.no_color:
        settings.color_mode = "off"
    if args.sound:
        settings.sound = True
    if args.text_speed:
        settings.text_speed = args.text_speed
    if args.reduced_motion:
        settings.reduced_motion = True
    if args.screen_reader:
        settings.screen_reader = True
    if args.difficulty:
        settings.difficulty = args.difficulty

    color = {"auto": None, "on": True, "off": False}[settings.color_mode]
    sound_player = SoundPlayer()
    # A real terminal remains the accessible presentation for screen readers.
    terminal = args.terminal or settings.screen_reader
    if args.pixel or args.screenshot:
        terminal = False
    options = dict(
        color=color,
        sound=settings.sound,
        fast=args.fast,
        text_speed=settings.text_speed,
        reduced_motion=settings.reduced_motion,
        screen_reader=settings.screen_reader if terminal else False,
    )
    if terminal:
        ui = TerminalUI(**options, checkpoint_support=True, sound_fn=sound_player.play)
    else:
        try:
            from .pixel_ui import PixelUI, launch_pixel_game
        except ModuleNotFoundError as error:
            if error.name != "pygame":
                raise
            raise SystemExit(
                'Install the pixel edition with: python3 -m pip install .\n'
                'Or play without installing packages: python3 -m roads_beneath_shadow --terminal'
            ) from None
        ui = PixelUI(**options)
    game: Game | None = None
    try:
        game = Game(
            ui,
            settings_manager=settings_manager,
            user_settings=settings,
            profile=ProfileManager(),
        )
        if terminal:
            game.run()
        else:
            try:
                launch_pixel_game(game, ui, screenshot=args.screenshot)
            except RuntimeError as error:
                raise SystemExit(str(error)) from None
    except (KeyboardInterrupt, InputClosed):
        message = "\n" + (
            game.interruption_notice()
            if game is not None
            else "Your journey has paused. Automatic recovery could not be checked."
        )
        if terminal:
            ui.write(message)
        else:
            print(message)


if __name__ == "__main__":
    main()
