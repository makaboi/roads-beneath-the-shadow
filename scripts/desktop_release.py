"""Build verified player archives and publish a complete desktop release in CI.

Only the plan and publish commands need GitHub authentication. Package smoke tests
run the frozen executable with isolated saves and dummy SDL devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform as host_platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from time import monotonic, perf_counter, sleep
import zipfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
GAME_NAME = "Roads-Beneath-the-Shadow"
PLATFORMS = ("Linux-x64", "Windows-x64", "macOS-Apple-Silicon", "macOS-Intel")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+\Z")
QUALITY_JOBS = {
    f"{system} / Python {version}"
    for system in ("macos-latest", "macos-15-intel", "ubuntu-latest", "windows-latest")
    for version in ("3.10", "3.13")
}


def read_project_version(path: Path) -> str:
    try:
        import tomllib
    except ModuleNotFoundError:
        # Python 3.10 has no TOML reader. Release versions use one literal,
        # three-part numeric value in [project]; reject other forms explicitly.
        version = None
        in_project = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_project = stripped == "[project]"
            elif in_project and re.match(r"version\s*=", stripped):
                match = re.fullmatch(r"version\s*=\s*(['\"])(\d+\.\d+\.\d+)\1\s*(?:#.*)?", stripped)
                if match is None or version is not None:
                    raise ValueError("Desktop releases require one literal numeric project version")
                version = match[2]
    else:
        with path.open("rb") as source:
            version = tomllib.load(source)["project"]["version"]
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("Desktop releases require a three-part numeric project version")
    return version


def project_version() -> str:
    return read_project_version(ROOT / "pyproject.toml")


def verify_version(version: str) -> None:
    if version != project_version():
        raise ValueError("The requested release version does not match pyproject.toml")


def github_repository() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY must identify the release repository")
    return repository


def github_commit() -> str:
    commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("GITHUB_SHA must identify the exact release commit")
    return commit


def github_api(path: str, *, missing_ok: bool = False, timeout: float = 60) -> dict | list[dict] | None:
    result = subprocess.run(
        ["gh", "api", f"repos/{github_repository()}/{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=timeout,
    )
    if result.returncode:
        if missing_ok and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(f"GitHub API request failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def release_for_tag(tag: str) -> dict | None:
    existing = github_api(f"releases/tags/{tag}", missing_ok=True)
    if existing is not None:
        if not isinstance(existing, dict):
            raise ValueError("GitHub returned an invalid release object")
        return existing
    # Before publication the tag might not exist. GitHub's tag lookup returns
    # 404 for that draft, even though the authenticated release list includes it.
    page = 1
    while True:
        releases = github_api(f"releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ValueError("GitHub returned an invalid release list")
        for release in releases:
            if release["tag_name"] == tag:
                return release
        if len(releases) < 100:
            return None
        page += 1


def verify_existing_tag(tag: str) -> None:
    reference = github_api(f"git/ref/tags/{tag}", missing_ok=True)
    if reference is None:
        return
    target = reference["object"]
    # An annotated tag can point to another tag; follow it to its commit.
    for _ in range(8):
        if target["type"] == "commit":
            if target["sha"] != github_commit():
                raise ValueError(
                    f"{tag} already names another commit; bump the project version "
                    "instead of replacing an existing release tag"
                )
            return
        if target["type"] != "tag":
            break
        tag_object = github_api(f"git/tags/{target['sha']}")
        assert tag_object is not None
        target = tag_object["object"]
    raise ValueError(f"{tag} does not resolve to a commit")


def plan_release(*, preview_only: bool = False) -> None:
    version = project_version()
    tag = f"v{version}"
    # A preview is an artifact-only build of the checked-out ref. It never
    # looks up or verifies a published tag, so an existing version is reusable.
    existing = None if preview_only else release_for_tag(tag)
    build = preview_only or existing is None or existing["draft"]
    if build and not preview_only:
        verify_existing_tag(tag)
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise ValueError("GITHUB_OUTPUT is required to plan an Actions release")
    with Path(output).open("a", encoding="utf-8") as target:
        target.write(f"version={version}\ntag={tag}\nbuild={str(build).lower()}\npublish={str(build and not preview_only).lower()}\n")
    if preview_only:
        print(f"Build and test desktop preview archives for {tag}; publication is disabled.")
    elif build:
        print(f"Build verified desktop downloads for {tag}.")
    else:
        print(f"{tag} is already published; leaving its downloads unchanged.")


def archive_name(platform: str) -> str:
    extension = ".tar.gz" if platform == "Linux-x64" else ".zip"
    return f"{GAME_NAME}-{platform}{extension}"


def archive_digest(archive: Path) -> str:
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_host(platform: str) -> None:
    machine = host_platform.machine().lower()
    expected_system = "win32" if platform.startswith("Windows-") else (
        "darwin" if platform.startswith("macOS-") else "linux"
    )
    expected_machines = ("arm64", "aarch64") if platform == "macOS-Apple-Silicon" else (
        "amd64", "x86_64"
    )
    if sys.platform != expected_system or machine not in expected_machines:
        raise ValueError(f"{platform} must be built on its matching OS and architecture")


def launcher_command(launcher: Path, platform: str, arguments: list[str]) -> list[str] | str:
    if platform == "Windows-x64":
        # cmd needs one quoted command string after /c; all launch arguments
        # here are generated by the smoke test, rather than player input.
        command = subprocess.list2cmdline([str(launcher), *arguments])
        interpreter = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe")])
        return f'{interpreter} /d /s /c "call {command}"'
    shell = "/bin/zsh" if platform.startswith("macOS-") else "/bin/sh"
    return [shell, str(launcher), *arguments]


def smoke_test(
    executable: Path, *, launcher: Path | None = None, platform: str | None = None,
    expected_version: str | None = None,
) -> dict:
    executable = executable.resolve()
    version = expected_version or project_version()
    if launcher is not None:
        launcher = launcher.resolve()
        if platform not in PLATFORMS:
            raise ValueError("A launcher smoke test needs its platform")
    timings = {}
    with tempfile.TemporaryDirectory(prefix="rbs-frozen-smoke-") as temporary:
        work = Path(temporary)
        environment = {
            **os.environ,
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "PYGAME_HIDE_SUPPORT_PROMPT": "1",
            "RBS_SAVE_DIR": str(work / "saves"),
        }
        def command(arguments: list[str]) -> list[str] | str:
            return launcher_command(launcher, platform, arguments) if launcher else [str(executable), *arguments]

        start = perf_counter()
        reported = subprocess.run(
            command(["--version"]), env=environment, cwd=work, check=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )
        timings["version_check"] = round(perf_counter() - start, 3)
        if reported.stdout != f"Roads Beneath the Shadow {version}\n":
            raise ValueError(f"Frozen version mismatch: expected {version}, got {reported.stdout.strip()!r}")
        start = perf_counter()
        decoded = subprocess.run(
            command(["--check-runtime-assets"]), env=environment, cwd=work, check=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )
        timings["runtime_decode"] = round(perf_counter() - start, 3)
        decoded_assets = json.loads(decoded.stdout)
        if not isinstance(decoded_assets, dict) or decoded_assets.get("audio_driver") != "dummy":
            raise ValueError("The frozen game did not verify its native resource decoders")
        for label, arguments in (
            ("asset_check", ["--check-install"]),
            ("pixel_render", ["--pixel", "--screenshot", str(work / "pixel-smoke.png")]),
        ):
            start = perf_counter()
            subprocess.run(
                command(arguments),
                env=environment,
                cwd=work,
                check=True,
                timeout=90,
            )
            timings[label] = round(perf_counter() - start, 3)
        screenshot = work / "pixel-smoke.png"
        if not screenshot.is_file():
            raise ValueError("The frozen pixel game did not render its title screen")
        # Pillow is already part of the build's test extra. Decode the whole
        # image so a truncated file with a PNG header cannot pass release QA.
        from PIL import Image

        with Image.open(screenshot) as image:
            if image.format != "PNG" or min(image.size) <= 0:
                raise ValueError("The frozen pixel screenshot is not a PNG")
            image.load()
            image_size = image.size
        start = perf_counter()
        terminal = subprocess.run(
            command(["--terminal", "--fast", "--no-color"]),
            input="6\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            cwd=work,
            check=True,
            timeout=90,
        )
        if "May a star shine upon your road." not in terminal.stdout:
            raise ValueError("The frozen terminal game did not reach its Quit action")
        timings["terminal_quit"] = round(perf_counter() - start, 3)
        print("Verified frozen assets, pixel rendering, and terminal input.")
    return {
        "version": version, "decoded_assets": decoded_assets, "screenshot_size": list(image_size),
        "seconds": timings, "through_launcher": launcher is not None,
    }


def local_readme_images(readme: Path) -> list[Path]:
    """Find portable embedded media so the extracted guide also works offline."""
    images = []
    root = readme.parent.resolve()
    pattern = r"!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)"
    for angled, plain in re.findall(pattern, readme.read_text(encoding="utf-8")):
        url = urlsplit(angled or plain)
        if url.scheme or url.netloc or not url.path:
            continue
        relative = PurePosixPath(unquote(url.path))
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError(f"README image path must stay inside the player folder: {relative}")
        image = Path(*relative.parts)
        if not (root / image).resolve().is_relative_to(root):
            raise ValueError(f"README image path leaves the player folder: {image}")
        if not (root / image).is_file():
            raise ValueError(f"README image is missing: {image}")
        if image not in images:
            images.append(image)
    return images


def assemble_archive(executable: Path, platform: str, version: str, output: Path) -> Path:
    if not (executable.parent / "_internal").is_dir():
        raise ValueError("Desktop downloads require a complete onedir build with _internal libraries")
    for name in ("THIRD-PARTY-NOTICES.md", "THIRD-PARTY-INVENTORY.json"):
        if not (executable.parent / name).is_file():
            raise ValueError(f"Prepare the build's third-party notices before packaging: {name}")
    build_directory = executable.parent.resolve()
    for path in executable.parent.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(build_directory):
            raise ValueError(f"A build link leaves the standalone folder: {path.name}")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / archive_name(platform)
    with tempfile.TemporaryDirectory(prefix="rbs-player-package-") as temporary:
        package = Path(temporary) / GAME_NAME
        # PyInstaller uses internal library/framework symlinks on Unix. Copy
        # their contents as regular files, preserving the loader's paths while
        # keeping the player archive safe for the strict extractor below.
        shutil.copytree(executable.parent, package, symlinks=False)
        bundled_executable = package / executable.name
        if platform != "Windows-x64":
            bundled_executable.chmod(0o755)
        for document in ("README.md", "CHANGELOG.md"):
            shutil.copy2(ROOT / document, package / document)
        for image in local_readme_images(ROOT / "README.md"):
            (package / image).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / image, package / image)
        font_license = ROOT / "roads_beneath_shadow" / "font_assets" / "LICENSE.txt"
        if font_license.is_file():
            shutil.copy2(font_license, package / "FONT-LICENSE.txt")
        if platform.startswith("macOS-"):
            launcher = package / "Play Roads Beneath the Shadow.command"
            shutil.copy2(ROOT / "Play Standalone.command", launcher)
            launcher.chmod(0o755)
            launch = "Double-click Play Roads Beneath the Shadow.command."
        elif platform == "Windows-x64":
            launcher = package / "Play Roads Beneath the Shadow.cmd"
            launcher.write_bytes(
                b'@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
                b'"Roads-Beneath-the-Shadow.exe" %*\r\n'
                b'set "RBS_LAUNCH_STATUS=%ERRORLEVEL%"\r\n'
                b'if not "%RBS_LAUNCH_STATUS%"=="0" pause\r\n'
                b'exit /b %RBS_LAUNCH_STATUS%\r\n'
            )
            launch = "Double-click Roads-Beneath-the-Shadow.exe."
        else:
            launcher = package / "Play Roads Beneath the Shadow.sh"
            launcher.write_text(
                '#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\n'
                'exec "./Roads-Beneath-the-Shadow" "$@"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            launch = "Run ./Roads-Beneath-the-Shadow from the extracted folder."
        (package / "START-HERE.txt").write_text(
            f"Roads Beneath the Shadow {version} — {platform}\n\n"
            f"Extract the complete archive first. {launch}\n"
            "Keep the executable and the complete _internal folder together.\n"
            "Python and separate game packages are not required.\n"
            "The game runs offline; a desktop display is required for pixel mode.\n"
            "Pass --terminal to play with terminal prompts.\n"
            "Read README.md for controls, saves, settings, and troubleshooting.\n",
            encoding="utf-8",
        )
        if platform == "Linux-x64":
            with tarfile.open(archive, "w:gz") as target:
                target.add(package, arcname=GAME_NAME)
        else:
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for source in sorted(package.rglob("*")):
                    if source.is_file():
                        target.write(source, source.relative_to(package.parent))
    checksum = archive_digest(archive)
    archive.with_name(f"{archive.name}.sha256").write_text(
        f"{checksum}  {archive.name}\n", encoding="ascii"
    )
    return archive


def extract_player_archive(archive: Path, platform: str, destination: Path) -> tuple[Path, Path]:
    """Extract the player download and verify its layout and launch permissions."""
    destination.mkdir(parents=True, exist_ok=True)

    def target(name: str) -> Path:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != GAME_NAME:
            raise ValueError(f"Invalid player archive path: {name}")
        return destination / path

    if platform == "Linux-x64":
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                output = target(member.name)
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    output.parent.mkdir(parents=True, exist_ok=True)
                    data = source.extractfile(member)
                    if data is None:
                        raise ValueError(f"Unreadable archive member: {member.name}")
                    with data, output.open("wb") as copied:
                        shutil.copyfileobj(data, copied)
                    output.chmod(member.mode & 0o777)
                else:
                    raise ValueError(f"Player archive contains a non-file member: {member.name}")
    else:
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                output = target(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Player archive contains a symbolic link: {member.filename}")
                if member.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as data, output.open("wb") as copied:
                        shutil.copyfileobj(data, copied)
                    if platform != "Windows-x64":
                        output.chmod(mode & 0o777)
    package = destination / GAME_NAME
    executable = package / (GAME_NAME + (".exe" if platform == "Windows-x64" else ""))
    launcher = package / (
        "Play Roads Beneath the Shadow.cmd" if platform == "Windows-x64" else
        "Play Roads Beneath the Shadow.command" if platform.startswith("macOS-") else
        "Play Roads Beneath the Shadow.sh"
    )
    required = [executable, launcher, *(package / name for name in (
        "START-HERE.txt", "README.md", "CHANGELOG.md", "THIRD-PARTY-NOTICES.md", "THIRD-PARTY-INVENTORY.json",
    ))]
    if (ROOT / "roads_beneath_shadow" / "font_assets" / "LICENSE.txt").is_file():
        required.append(package / "FONT-LICENSE.txt")
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ValueError("The player archive is incomplete: " + ", ".join(missing))
    if not (package / "_internal").is_dir():
        raise ValueError("The player archive is incomplete: _internal shared libraries")
    if __package__:
        from .third_party import verify_inventory
    else:
        from third_party import verify_inventory
    verify_inventory(package)
    local_readme_images(package / "README.md")
    if platform != "Windows-x64":
        for path in (executable, launcher):
            if not path.stat().st_mode & 0o111:
                raise ValueError(f"The player archive lost execute permission: {path.name}")
    return executable, launcher


def verify_player_archive(archive: Path, platform: str, *, expected_version: str | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="rbs player download with spaces ") as temporary:
        executable, launcher = extract_player_archive(archive, platform, Path(temporary))
        return smoke_test(executable, launcher=launcher, platform=platform, expected_version=expected_version)


def package_release(platform: str, version: str, output: Path) -> None:
    verify_version(version)
    verify_host(platform)
    suffix = ".exe" if platform == "Windows-x64" else ""
    bundle = ROOT / "dist" / GAME_NAME
    executable = bundle / f"{GAME_NAME}{suffix}"
    if not executable.is_file():
        raise FileNotFoundError(f"Build the standalone executable first: {executable}")
    if __package__:
        from .third_party import prepare_bundle
    else:
        from third_party import prepare_bundle
    notice_inventory = prepare_bundle(bundle, platform, ROOT / "build" / GAME_NAME / "Analysis-00.toc")
    binary_report = smoke_test(executable, expected_version=version)
    archive = assemble_archive(executable, platform, version, output)
    player_report = verify_player_archive(archive, platform, expected_version=version)
    archive.with_name(f"{archive.name}.qa.json").write_text(
        json.dumps({
            "platform": platform, "version": version, "source_commit": os.environ.get("GITHUB_SHA"),
            "archive": {"name": archive.name, "sha256": archive_digest(archive), "size_bytes": archive.stat().st_size},
            "binary": binary_report, "extracted_launcher": player_report,
            "third_party": {
                "inventory_sha256": archive_digest(bundle / "THIRD-PARTY-INVENTORY.json"),
                "unresolved": notice_inventory["runtime"]["unresolved"],
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Created {archive.name} and its SHA-256 checksum.")
    unresolved = notice_inventory["runtime"]["unresolved"]
    print(f"Retained {len(notice_inventory['source_archives'])} third-party source archives; unresolved runtime notices: {len(unresolved)}.")
    for issue in unresolved:
        print(f"  {issue['component']}: {issue['reason']}")


def verified_downloads(output: Path) -> list[Path]:
    downloads: list[Path] = []
    for platform in PLATFORMS:
        archive = output / archive_name(platform)
        checksum = archive.with_name(f"{archive.name}.sha256")
        if not archive.is_file() or not checksum.is_file():
            raise ValueError(f"The release is incomplete: {archive.name}")
        expected = archive_digest(archive)
        if checksum.read_text(encoding="ascii") != f"{expected}  {archive.name}\n":
            raise ValueError(f"Archive checksum mismatch: {archive.name}")
        downloads.extend((archive, checksum))
    return downloads


def verify_notice_gate(output: Path, version: str) -> None:
    """Allow preview inspection, but stop publication with unresolved notices."""
    for platform in PLATFORMS:
        archive = output / archive_name(platform)
        report_path = archive.with_name(f"{archive.name}.qa.json")
        if not report_path.is_file():
            raise ValueError(f"The release has no native third-party QA report: {report_path.name}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            report.get("platform") != platform or report.get("version") != version
            or report.get("source_commit") != github_commit()
            or report.get("archive", {}).get("sha256") != archive_digest(archive)
        ):
            raise ValueError(f"Native third-party QA does not match the exact archive/commit: {platform}")
        notices = report.get("third_party", {})
        if not isinstance(notices.get("unresolved"), list) or notices["unresolved"]:
            raise ValueError(f"Native third-party notices require review before publication: {platform}")
        if not re.fullmatch(r"[0-9a-f]{64}", notices.get("inventory_sha256", "")):
            raise ValueError(f"Native third-party QA has no inventory hash: {platform}")
        inventory_name = f"{GAME_NAME}/THIRD-PARTY-INVENTORY.json"
        try:
            if platform == "Linux-x64":
                with tarfile.open(archive, "r:gz") as source:
                    members = [member for member in source.getmembers() if member.name == inventory_name]
                    if len(members) != 1 or not members[0].isfile() or members[0].size > 16 * 1024 * 1024:
                        raise ValueError("The archive must contain one regular third-party inventory")
                    with source.extractfile(members[0]) as incoming:
                        inventory_bytes = incoming.read()
            else:
                with zipfile.ZipFile(archive) as source:
                    members = [member for member in source.infolist() if member.filename == inventory_name]
                    if len(members) != 1 or members[0].is_dir() or stat.S_ISLNK(members[0].external_attr >> 16) or members[0].file_size > 16 * 1024 * 1024:
                        raise ValueError("The archive must contain one regular third-party inventory")
                    inventory_bytes = source.read(members[0])
            inventory = json.loads(inventory_bytes)
        except (tarfile.TarError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeError) as error:
            raise ValueError(f"The archive has no readable third-party inventory: {platform}") from error
        if hashlib.sha256(inventory_bytes).hexdigest() != notices["inventory_sha256"]:
            raise ValueError(f"The packaged third-party inventory does not match native QA: {platform}")
        packaged_unresolved = inventory.get("runtime", {}).get("unresolved")
        if inventory.get("schema_version") != 1 or not isinstance(packaged_unresolved, list) or packaged_unresolved != notices["unresolved"]:
            raise ValueError(f"The packaged third-party notice results do not match native QA: {platform}")


def verify_quality_gate(*, timeout: float = 600, poll_interval: float = 10) -> dict:
    """Require all eight quality jobs on the exact main commit before publication."""
    commit = github_commit()
    deadline = monotonic() + timeout
    path = f"actions/workflows/quality.yml/runs?head_sha={commit}&event=push&branch=main&per_page=100"
    waiting = False

    def fetch(path: str):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for the exact-commit Quality Gate; the release remains private")
        try:
            return github_api(path, timeout=min(60, remaining))
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("Quality Gate metadata did not respond in time; the release remains private") from error

    while True:
        response = fetch(path)
        if not isinstance(response, dict) or not isinstance(response.get("workflow_runs"), list):
            raise ValueError("GitHub returned an invalid Quality Gate run list")
        matches = [
            run for run in response["workflow_runs"]
            if run.get("head_sha") == commit and run.get("head_branch") == "main" and run.get("event") == "push"
        ]
        latest = max(matches, key=lambda run: run["id"], default=None)
        if latest is not None and latest["status"] == "completed":
            if latest["conclusion"] != "success":
                raise ValueError(
                    f"The exact-commit Quality Gate ended with {latest['conclusion']}: "
                    f"{latest.get('html_url', latest['id'])}"
                )
            jobs = {}
            page = 1
            while True:
                response = fetch(f"actions/runs/{latest['id']}/jobs?filter=all&per_page=100&page={page}")
                if not isinstance(response, dict) or not isinstance(response.get("jobs"), list):
                    raise ValueError("GitHub returned an invalid Quality Gate job list")
                # Re-running failed jobs can leave successful matrix cells in
                # an earlier attempt. Keep each cell's newest execution from
                # this exact run, including failed or skipped replacements.
                for job in response["jobs"]:
                    previous = jobs.get(job["name"])
                    rank = (job.get("run_attempt", 1), job.get("id", 0))
                    if previous is None or rank > (previous.get("run_attempt", 1), previous.get("id", 0)):
                        jobs[job["name"]] = job
                if len(response["jobs"]) < 100:
                    break
                page += 1
            incomplete = sorted(
                name for name in QUALITY_JOBS
                if name not in jobs or jobs[name]["status"] != "completed" or jobs[name]["conclusion"] != "success"
            )
            if incomplete:
                raise ValueError("Quality Gate did not verify every required platform/Python job: " + ", ".join(incomplete))
            print(f"Quality Gate verified the exact release commit across {len(QUALITY_JOBS)} jobs.")
            return {"run_id": latest["id"], "run_attempt": latest.get("run_attempt", 1), "verified_jobs": len(QUALITY_JOBS)}
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for the exact-commit Quality Gate; the release remains private")
        if not waiting:
            print(f"Waiting for Quality Gate on {commit[:12]}; the release remains private.", flush=True)
            waiting = True
        sleep(min(poll_interval, remaining))


def publish_release(version: str, output: Path) -> None:
    verify_version(version)
    downloads = verified_downloads(output)
    verify_notice_gate(output, version)
    tag = f"v{version}"
    existing = release_for_tag(tag)
    if existing is not None and not existing["draft"]:
        print(f"{tag} is already published; leaving its downloads unchanged.")
        return
    verify_existing_tag(tag)
    environment = {**os.environ, "GH_REPO": github_repository()}
    if existing is None:
        subprocess.run(
            [
                "gh", "release", "create", tag, "--draft", "--target", github_commit(),
                "--title", f"Roads Beneath the Shadow {tag}", "--generate-notes",
            ],
            env=environment,
            check=True,
        )
        existing = release_for_tag(tag)
    else:
        # A failed publishing attempt can leave a private draft. All archives
        # have just been rebuilt; name their exact commit before retrying.
        subprocess.run(
            ["gh", "release", "edit", tag, "--draft", "--target", github_commit()],
            env=environment,
            check=True,
        )
    if existing is None or not existing["draft"]:
        raise ValueError("GitHub did not create an unpublished release draft")
    release_path = f"releases/{existing['id']}"
    draft = github_api(release_path)
    if (
        not isinstance(draft, dict) or not draft["draft"]
        or draft["tag_name"] != tag or draft["target_commitish"] != github_commit()
    ):
        raise ValueError("The release draft does not name the exact rebuilt commit")
    subprocess.run(
        ["gh", "release", "upload", tag, *(str(path) for path in downloads), "--clobber"],
        env=environment,
        check=True,
    )
    uploaded = github_api(release_path)
    if (
        not isinstance(uploaded, dict) or not uploaded["draft"]
        or uploaded["tag_name"] != tag or uploaded["target_commitish"] != github_commit()
    ):
        raise ValueError("The release must remain a draft until every download is verified")
    assets = {asset["name"]: asset for asset in uploaded["assets"]}
    unexpected = sorted(assets.keys() - {download.name for download in downloads})
    if unexpected:
        raise ValueError("The release draft contains unexpected downloads: " + ", ".join(unexpected))
    for download in downloads:
        asset = assets.get(download.name)
        if asset is None or asset["state"] != "uploaded" or asset["size"] != download.stat().st_size:
            raise ValueError(f"GitHub did not receive the complete download: {download.name}")
        if asset.get("digest") != f"sha256:{archive_digest(download)}":
            raise ValueError(f"GitHub download checksum mismatch: {download.name}")
    verify_quality_gate()
    # Waiting for CI can take several minutes. Preserve a tag created during
    # that wait just as strictly as one present at the start of publication.
    verify_existing_tag(tag)
    subprocess.run(
        ["gh", "release", "edit", tag, "--draft=false", "--latest"],
        env=environment,
        check=True,
    )
    print(f"Published {tag} with all four desktop downloads and checksums.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="plan a release or an artifact-only desktop preview")
    plan.add_argument("--preview-only", action="store_true", help="build the checked-out version without release or tag lookups")
    package = commands.add_parser("package", help="smoke-test and archive a frozen executable")
    package.add_argument("--platform", choices=PLATFORMS, required=True)
    package.add_argument("--version", required=True)
    package.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify-archive", help="extract and smoke-test a player archive on its target platform")
    verify.add_argument("--platform", choices=PLATFORMS, required=True)
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--version", help="expected game version (defaults to pyproject.toml)")
    publish = commands.add_parser("publish", help="publish every verified archive together")
    publish.add_argument("--version", required=True)
    publish.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        plan_release(preview_only=args.preview_only)
    elif args.command == "package":
        package_release(args.platform, args.version, args.output_dir)
    elif args.command == "verify-archive":
        verify_host(args.platform)
        print(json.dumps(verify_player_archive(args.archive.resolve(), args.platform, expected_version=args.version), indent=2))
    else:
        publish_release(args.version, args.output_dir)


if __name__ == "__main__":
    main()
