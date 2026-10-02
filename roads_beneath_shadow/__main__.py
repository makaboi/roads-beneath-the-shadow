"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .app import Game
from .audio import SoundPlayer
from .profile import ProfileManager
from .settings import SettingsManager
from .ui import InputClosed, TerminalUI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Play The Lord of the Rings: Roads Beneath the Shadow")
    presentation = parser.add_mutually_exclusive_group()
    presentation.add_argument("--pixel", action="store_true", help="open the pixel-art desktop game (default)")
    presentation.add_argument("--terminal", action="store_true", help="play the original dependency-free terminal edition")
    parser.add_argument("--screenshot", type=Path, help="render the pixel-art main menu to a PNG and exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI terminal colors")
    parser.add_argument("--sound", action="store_true", help="enable the original retro sound cues")
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.screenshot and (args.terminal or args.screen_reader):
        parser.error("--screenshot requires pixel-art mode")
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
        print(f"Installation verified: {len(SoundPlayer.CUES)} sound cues and pixel-art scenes are available.")
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
        ui = TerminalUI(**options, sound_fn=sound_player.play)
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
        message = "\nYour journey has paused. Unsaved progress was not kept."
        if terminal:
            ui.write(message)
        else:
            print(message)


if __name__ == "__main__":
    main()
