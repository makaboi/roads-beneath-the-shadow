"""Build verified player archives and publish a complete desktop release in CI.

Only the plan and publish commands need GitHub authentication. Package smoke tests
run the frozen executable with isolated saves and dummy SDL devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform as host_platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
GAME_NAME = "Roads-Beneath-the-Shadow"
PLATFORMS = ("Linux-x64", "Windows-x64", "macOS-Apple-Silicon", "macOS-Intel")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+\Z")


def project_version() -> str:
    # The release workflow runs Python 3.13. Keep this import local so its
    # protocol and archive helpers can also be tested on the game's Python 3.10.
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("Desktop releases require a three-part numeric project version")
    return version


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


def github_api(path: str, *, missing_ok: bool = False) -> dict | list[dict] | None:
    result = subprocess.run(
        ["gh", "api", f"repos/{github_repository()}/{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
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


def plan_release() -> None:
    version = project_version()
    tag = f"v{version}"
    existing = release_for_tag(tag)
    build = existing is None or existing["draft"]
    if build:
        verify_existing_tag(tag)
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise ValueError("GITHUB_OUTPUT is required to plan an Actions release")
    with Path(output).open("a", encoding="utf-8") as target:
        target.write(f"version={version}\ntag={tag}\nbuild={str(build).lower()}\n")
    if build:
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


def smoke_test(executable: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="rbs-frozen-smoke-") as temporary:
        work = Path(temporary)
        environment = {
            **os.environ,
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "PYGAME_HIDE_SUPPORT_PROMPT": "1",
            "RBS_SAVE_DIR": str(work / "saves"),
        }
        for arguments in (
            ["--check-install"],
            ["--pixel", "--screenshot", str(work / "pixel-smoke.png")],
        ):
            subprocess.run(
                [str(executable), *arguments],
                env=environment,
                cwd=work,
                check=True,
                timeout=90,
            )
        screenshot = work / "pixel-smoke.png"
        if not screenshot.is_file() or screenshot.stat().st_size < 8:
            raise ValueError("The frozen pixel game did not render its title screen")
        if screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("The frozen pixel screenshot is not a PNG")
        terminal = subprocess.run(
            [str(executable), "--terminal", "--fast", "--no-color"],
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
        print("Verified frozen assets, pixel rendering, and terminal input.")


def assemble_archive(executable: Path, platform: str, version: str, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    archive = output / archive_name(platform)
    with tempfile.TemporaryDirectory(prefix="rbs-player-package-") as temporary:
        package = Path(temporary) / GAME_NAME
        package.mkdir()
        bundled_executable = package / executable.name
        shutil.copy2(executable, bundled_executable)
        if platform != "Windows-x64":
            bundled_executable.chmod(0o755)
        for document in ("README.md", "CHANGELOG.md"):
            shutil.copy2(ROOT / document, package / document)
        if platform.startswith("macOS-"):
            launcher = package / "Play Roads Beneath the Shadow.command"
            shutil.copy2(ROOT / "Play Standalone.command", launcher)
            launcher.chmod(0o755)
            launch = "Double-click Play Roads Beneath the Shadow.command."
        elif platform == "Windows-x64":
            launcher = package / "Play Roads Beneath the Shadow.cmd"
            launcher.write_bytes(
                b'@echo off\r\ncd /d "%~dp0"\r\n'
                b'"Roads-Beneath-the-Shadow.exe" %*\r\n'
                b'if errorlevel 1 pause\r\n'
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


def package_release(platform: str, version: str, output: Path) -> None:
    verify_version(version)
    verify_host(platform)
    suffix = ".exe" if platform == "Windows-x64" else ""
    executable = ROOT / "dist" / f"{GAME_NAME}{suffix}"
    if not executable.is_file():
        raise FileNotFoundError(f"Build the standalone executable first: {executable}")
    smoke_test(executable)
    archive = assemble_archive(executable, platform, version, output)
    print(f"Created {archive.name} and its SHA-256 checksum.")


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


def publish_release(version: str, output: Path) -> None:
    verify_version(version)
    downloads = verified_downloads(output)
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
    for download in downloads:
        asset = assets.get(download.name)
        if asset is None or asset["state"] != "uploaded" or asset["size"] != download.stat().st_size:
            raise ValueError(f"GitHub did not receive the complete download: {download.name}")
    subprocess.run(
        ["gh", "release", "edit", tag, "--draft=false", "--latest"],
        env=environment,
        check=True,
    )
    print(f"Published {tag} with all four desktop downloads and checksums.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="skip a version that already has a published release")
    package = commands.add_parser("package", help="smoke-test and archive a frozen executable")
    package.add_argument("--platform", choices=PLATFORMS, required=True)
    package.add_argument("--version", required=True)
    package.add_argument("--output-dir", type=Path, required=True)
    publish = commands.add_parser("publish", help="publish every verified archive together")
    publish.add_argument("--version", required=True)
    publish.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        plan_release()
    elif args.command == "package":
        package_release(args.platform, args.version, args.output_dir)
    else:
        publish_release(args.version, args.output_dir)


if __name__ == "__main__":
    main()
