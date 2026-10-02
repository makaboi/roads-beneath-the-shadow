"""Verify refreshed scene references with the pinned upstream converter.

Run from any directory with --converter /path/to/ascii-image-converter.
This authoring check is separate from the dependency-free game runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from roads_beneath_shadow import artwork, journey_artwork, part_two_artwork  # noqa: E402

ART_MODULES = {"artwork": artwork, "part_two_artwork": part_two_artwork}


def clean_output(output: str) -> str:
    rows = [row.rstrip() for row in output.splitlines()]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return "\n".join(rows)


def verify(converter: str) -> None:
    source_root = ROOT / "assets" / "ascii-sources"
    for source_dir, module in ((source_root, artwork), (source_root / "lanterns", journey_artwork)):
        verify_manifest(converter, source_dir, module)


def verify_manifest(converter: str, source_dir: Path, module) -> None:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    version = subprocess.run([converter, "--version"], check=True, text=True, capture_output=True)
    expected = "v" + manifest["converter"]["version"]
    if version.stdout.strip() != expected:
        raise ValueError(f"Expected converter {expected}, got {version.stdout.strip()!r}")
    for entry in manifest["entries"]:
        owning_module = ART_MODULES[entry["module"]] if "module" in entry else module
        source = source_dir / entry["filename"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["source_sha256"]:
            raise ValueError(f"Reference changed: {source.name}")
        candidates = []
        for negative in (False, True):
            command = [converter, str(source), *manifest["converter"]["arguments"]]
            if negative:
                command.append("--negative")
            result = subprocess.run(command, check=True, text=True, capture_output=True)
            body = clean_output(result.stdout)
            stage_top = next((index for index, row in enumerate(result.stdout.splitlines()) if row.strip()), 0)
            density = sum(character not in " \n" for character in body)
            candidates.append((density, negative, body, stage_top))
        _density, negative, body, stage_top = min(candidates)
        committed = getattr(owning_module, entry["raw_constant"]).strip("\n")
        if body != committed or negative != entry["negative"]:
            raise ValueError(f"Art is not the exact sparse conversion: {entry['raw_constant']}")
        if hashlib.sha256(body.encode()).hexdigest() != entry["raw_sha256"]:
            raise ValueError(f"Raw art checksum changed: {entry['raw_constant']}")
        if "stage_top" in entry and stage_top != entry["stage_top"]:
            raise ValueError(f"Animation origin changed: {entry['raw_constant']}")
        print(f"Verified {entry['raw_constant']}: exact {expected} output, negative={negative}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--converter", default="ascii-image-converter")
    verify(parser.parse_args().converter)
