"""Verify a regular game installation without importing the source checkout.

Run after ``python -m pip install .``. The probe and game run in isolated Python
processes from a temporary directory, with dummy SDL devices and separate saves.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter

if __package__:
    from .desktop_release import archive_digest, project_version
else:
    from desktop_release import archive_digest, project_version


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "roads_beneath_shadow"
RESOURCE_DIRECTORIES = ("audio_assets", "pixel_assets", "font_assets")
CONSOLE_COMMAND = "roads-beneath-shadow"
CONSOLE_TARGET = "roads_beneath_shadow.__main__:main"
PROBE = """
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sysconfig
import roads_beneath_shadow

package = Path(roads_beneath_shadow.__file__).resolve().parent
distribution = importlib.metadata.distribution('roads-beneath-the-shadow')
entrypoints = {entry.name: entry.value for entry in distribution.entry_points if entry.group == 'console_scripts'}
console = Path(sysconfig.get_path('scripts')) / ('roads-beneath-shadow.exe' if os.name == 'nt' else 'roads-beneath-shadow')
files = {path for path in package.rglob('*.py') if path.is_file()}
for directory in ('audio_assets', 'pixel_assets', 'font_assets'):
    files.update(path for path in (package / directory).rglob('*')
                 if path.is_file() and not any(part.startswith('.') for part in path.relative_to(package).parts))
manifest = {}
for path in sorted(files):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    manifest[path.relative_to(package).as_posix()] = digest.hexdigest()
print(json.dumps({'origin': str(package), 'version': distribution.version,
                  'runtime_version': roads_beneath_shadow.__version__, 'entrypoints': entrypoints,
                  'console_launcher': str(console), 'files': manifest}))
"""


def source_manifest(package: Path = PACKAGE) -> dict[str, str]:
    files = {path for path in package.rglob("*.py") if path.is_file()}
    for directory in RESOURCE_DIRECTORIES:
        files.update(
            path for path in (package / directory).rglob("*")
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(package).parts)
        )
    return {path.relative_to(package).as_posix(): archive_digest(path) for path in sorted(files)}


def validate_installation(
    expected: dict[str, str], installed: dict, version: str, *, source_package: Path = PACKAGE,
) -> None:
    origin = Path(installed["origin"]).resolve()
    if origin == source_package.resolve() or origin.is_relative_to(source_package.resolve()):
        raise ValueError("The isolated interpreter imported the checkout; install a regular wheel first")
    if installed["version"] != version:
        raise ValueError(f"Installed version {installed['version']} does not match source version {version}")
    if installed["runtime_version"] != version:
        raise ValueError(f"Runtime version {installed['runtime_version']} does not match installed version {version}")
    if installed["entrypoints"].get(CONSOLE_COMMAND) != CONSOLE_TARGET:
        raise ValueError(f"The installed {CONSOLE_COMMAND} command is missing or names the wrong entry point")
    actual = installed["files"]
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys() if actual[name] != expected[name])
    if missing or extra or changed:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("stale files: " + ", ".join(extra))
        if changed:
            details.append("different bytes: " + ", ".join(changed))
        raise ValueError("Installed code or resources differ from the checkout (" + "; ".join(details) + ")")


def check_installation(interpreter: Path, *, expected_version: str | None = None) -> dict:
    version = expected_version or project_version()
    expected = source_manifest()
    timings = {}
    with tempfile.TemporaryDirectory(prefix="rbs installed candidate ") as temporary:
        work = Path(temporary)
        environment = {
            **os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
            "PYGAME_HIDE_SUPPORT_PROMPT": "1", "RBS_SAVE_DIR": str(work / "saves"),
        }
        # The console script does not use Python's -I flag. Prevent an inherited
        # source-path override from making that script import the checkout.
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)

        def run(label: str, arguments: list[str], *, input_text: str | None = None, executable: Path | None = None):
            start = perf_counter()
            command = [str(executable), *arguments] if executable else [str(interpreter), "-I", *arguments]
            result = subprocess.run(
                command, cwd=work, env=environment,
                input=input_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, check=False, timeout=90,
            )
            timings[label] = round(perf_counter() - start, 3)
            if result.returncode:
                raise RuntimeError(f"{label} failed outside the checkout:\n{result.stderr.strip()}")
            return result

        probe = json.loads(run("installed_files", ["-c", PROBE]).stdout)
        validate_installation(expected, probe, version)
        console = Path(probe["console_launcher"])
        if not console.is_file():
            raise ValueError(f"The installed console launcher is missing: {console}")
        reported = run("cli_version", ["--version"], executable=console)
        if reported.stdout != f"Roads Beneath the Shadow {version}\n":
            raise ValueError("The installed console command reports the wrong game version")
        run("console_entrypoint", ["--check-install"], executable=console)
        run("asset_check", ["-m", "roads_beneath_shadow", "--check-install"])
        decoded_assets = json.loads(run("runtime_decode", ["-m", "roads_beneath_shadow", "--check-runtime-assets"]).stdout)
        if not isinstance(decoded_assets, dict) or decoded_assets.get("audio_driver") != "dummy":
            raise ValueError("The installed game did not verify its native resource decoders")
        screenshot = work / "installed title.png"
        run("pixel_render", ["-m", "roads_beneath_shadow", "--pixel", "--screenshot", str(screenshot)])
        decoded = run(
            "decode_screenshot",
            ["-c", "import pygame,json,sys; image=pygame.image.load(sys.argv[1]); print(json.dumps(image.get_size()))", str(screenshot)],
        )
        image_size = json.loads(decoded.stdout)
        if len(image_size) != 2 or min(image_size) <= 0:
            raise ValueError("The installed pixel game did not produce a readable image")
        terminal = run(
            "terminal_quit", ["-m", "roads_beneath_shadow", "--terminal", "--fast", "--no-color"], input_text="6\n",
        )
        if "May a star shine upon your road." not in terminal.stdout:
            raise ValueError("The installed terminal game did not reach its Quit action")
    return {
        "version": version, "installed_origin": probe["origin"], "verified_files": len(expected),
        "decoded_assets": decoded_assets, "screenshot_size": image_size, "seconds": timings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="interpreter containing the installed wheel")
    parser.add_argument("--expected-version", help="expected project version (defaults to pyproject.toml)")
    parser.add_argument("--report", type=Path, help="write the verification and timing report as JSON")
    args = parser.parse_args()
    # Resolving a venv's interpreter symlink would select the base Python and
    # lose that venv's installed packages. Make it absolute without dereferencing.
    report = check_installation(args.python.absolute(), expected_version=args.expected_version)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Verified installed {report['version']}: {report['verified_files']} code/resource files, pixel rendering, and terminal input.")


if __name__ == "__main__":
    main()
