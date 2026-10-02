"""Decode packaged pixel resources without opening a display or playing audio.

This diagnostic is separate from normal gameplay. It exercises the SDL image,
font, and mixer libraries inside installed wheels and frozen player downloads.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

from .audio import SoundPlayer
from .pixel_theme import FONT_FILES
from .pixel_world import (
    CHARACTER_ATLAS_ROWS, CHARACTER_CELL, DEPTH_CELL, DEPTH_COLUMNS, DEPTH_OBJECTS,
    MOTION_CHARACTERS, MOTION_FRAMES, MOTION_ROWS, ORIGIN_PORTRAITS, WORLD_MAPS, WORLD_SIZE,
)
from .soundscapes import TRACKS


PACKAGE_DIRECTORY = Path(__file__).resolve().parent


def expected_image_sizes(manifest: dict) -> dict[str, tuple[int, int]]:
    resolution = manifest.get("resolution")
    if not isinstance(resolution, list) or len(resolution) != 2 or any(type(value) is not int or value <= 0 for value in resolution):
        raise ValueError("manifest.json contains an invalid pixel resolution")
    scenes = []
    for category in ("environment_scenes", "encounter_scenes", "original_pixel_props", "battle_backgrounds", "additional_scenes"):
        values = manifest.get(category, [] if category == "additional_scenes" else None)
        if not isinstance(values, list) or any(not isinstance(name, str) or re.fullmatch(r"[a-z0-9-]+", name) is None for name in values):
            raise ValueError("manifest.json contains invalid pixel scene names")
        scenes.extend(values)
    expected = {f"{name}.png": tuple(resolution) for name in scenes}
    sheets = manifest.get("sprite_sheets", {})
    if not isinstance(sheets, dict):
        raise ValueError("manifest.json contains invalid sprite sheet geometry")
    for name, dimensions in sheets.items():
        if (not isinstance(name, str) or re.fullmatch(r"world-[a-z0-9-]+", name) is None or
            not isinstance(dimensions, list) or len(dimensions) != 2 or
            any(type(value) is not int or value <= 0 for value in dimensions)):
            raise ValueError("manifest.json contains invalid sprite sheet geometry")
        expected[f"{name}.png"] = tuple(dimensions)
    expected.update({f"world-{name}.png": WORLD_SIZE for name in WORLD_MAPS})
    expected["world-characters.png"] = (4 * CHARACTER_CELL[0], (max(CHARACTER_ATLAS_ROWS.values()) + 1) * CHARACTER_CELL[1])
    expected["world-motion.png"] = (MOTION_FRAMES * CHARACTER_CELL[0], len(MOTION_CHARACTERS) * MOTION_ROWS * CHARACTER_CELL[1])
    expected["world-portraits.png"] = (len(ORIGIN_PORTRAITS) * CHARACTER_CELL[0], CHARACTER_CELL[1])
    depth_rows = (len(DEPTH_OBJECTS) + DEPTH_COLUMNS - 1) // DEPTH_COLUMNS
    expected["world-depth.png"] = (DEPTH_COLUMNS * DEPTH_CELL[0], depth_rows * DEPTH_CELL[1])
    return expected


def verify_runtime_assets(*, package_directory: Path | None = None) -> dict:
    """Check real decoding, preserving driver selection and existing font state.

Call this before starting the game's audio. It temporarily selects SDL's dummy
audio device, decodes WAVs into memory, and never plays a mixer channel.
"""
    package = package_directory or PACKAGE_DIRECTORY
    pixels = package / "pixel_assets"
    fonts = package / "font_assets"
    audio = package / "audio_assets"
    manifest_path = pixels / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Unable to read manifest.json: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must describe the packaged pixel scenes")
    expected_images = expected_image_sizes(manifest)
    required = [*(pixels / name for name in expected_images), *(fonts / name for name in FONT_FILES)]
    required.extend(audio / name for name in set(SoundPlayer.CUES.values()) | set(TRACKS.values()))
    missing = sorted(path.name for path in required if not path.is_file())
    if missing:
        raise ValueError("Runtime assets are missing: " + ", ".join(missing))
    images = sorted(pixels.glob("*.png"))
    font_files = sorted(fonts.glob("*.ttf"))
    wav_files = sorted(audio.glob("*.wav"))
    metadata = sorted(pixels.glob("*.json"))
    previous_driver = os.environ.get("SDL_AUDIODRIVER")
    previous_prompt = os.environ.get("PYGAME_HIDE_SUPPORT_PROMPT")
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    pg = None
    initialized_font = False
    initialized_mixer = False
    try:
        try:
            import pygame as pg
        except ImportError as error:
            raise RuntimeError("pygame-ce is required to verify the pixel runtime") from error
        if pg.mixer.get_init() is not None:
            raise RuntimeError("Run the runtime-assets diagnostic before game audio is initialized")
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        for path in metadata:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ValueError(f"Unable to read {path.name}: {error}") from error
        for path in images:
            try:
                image = pg.image.load(str(path))
                size = image.get_size()
                if min(size) <= 0 or path.name in expected_images and size != expected_images[path.name]:
                    raise ValueError(f"unexpected geometry {size}; expected {expected_images.get(path.name)}")
            except (OSError, ValueError, pg.error) as error:
                raise ValueError(f"Unable to decode {path.name}: {error}") from error
        if not pg.font.get_init():
            initialized_font = True
            pg.font.init()
        for path in font_files:
            font = None
            try:
                # Load the bundled TTF directly: a system-font fallback must
                # not conceal a damaged or omitted release font.
                font = pg.font.Font(str(path), 17)
                rendered = font.render("A traveller’s road — an eight-pointed star", True, (239, 225, 188))
                if min(rendered.get_size()) <= 0:
                    raise ValueError("font produced no glyphs")
            except (OSError, ValueError, pg.error) as error:
                raise ValueError(f"Unable to decode {path.name}: {error}") from error
            finally:
                # SDL_ttf keeps the source file open for the Font's lifetime.
                # Release it while the font subsystem is still initialized,
                # including when a later decoder leaves a traceback alive.
                font = None
        initialized_mixer = True
        pg.mixer.init(frequency=16_000, size=-16, channels=2, buffer=512)
        for path in wav_files:
            sound = None
            try:
                sound = pg.mixer.Sound(str(path))
                if sound.get_length() <= 0 or not sound.get_raw():
                    raise ValueError("sound contains no decoded samples")
            except (OSError, ValueError, pg.error) as error:
                raise ValueError(f"Unable to decode {path.name}: {error}") from error
            finally:
                sound = None
        return {
            "images": len(images), "world_maps": len(WORLD_MAPS), "fonts": len(font_files),
            "audio": len(wav_files), "metadata": len(metadata), "audio_driver": "dummy",
        }
    finally:
        if pg is not None:
            if initialized_mixer:
                pg.mixer.quit()
            if initialized_font:
                pg.font.quit()
        for name, previous in (("SDL_AUDIODRIVER", previous_driver), ("PYGAME_HIDE_SUPPORT_PROMPT", previous_prompt)):
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
