import os
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from scripts import desktop_release, third_party


def native_platform():
    if os.name == "nt":
        return "Windows-x64"
    if sys.platform == "darwin":
        return "macOS-Apple-Silicon" if platform.machine().lower() == "arm64" else "macOS-Intel"
    return "Linux-x64"


class PlayerArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rbs archive tests ")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.platform = native_platform()
        build = self.work / "build" / desktop_release.GAME_NAME
        (build / "_internal").mkdir(parents=True)
        library = build / "_internal" / "shared-library.bin"
        library.write_bytes(b"replaceable runtime library fixture")
        (build / "THIRD-PARTY-NOTICES.md").write_text("Runtime licenses and sources.\n")
        (build / "THIRD-PARTY-INVENTORY.json").write_text(json.dumps({
            "schema_version": 1, "payload": [{
                "path": "_internal/shared-library.bin", "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            }], "source_archives": [],
        }))
        self.binary = build / (desktop_release.GAME_NAME + (".exe" if os.name == "nt" else ""))
        self.binary.write_bytes(b"standalone executable fixture")
        self.archive = desktop_release.assemble_archive(self.binary, self.platform, "0.5.0", self.work / "downloads")

    def test_archive_round_trip_keeps_binary_guides_and_launch_permissions(self):
        executable, launcher = desktop_release.extract_player_archive(self.archive, self.platform, self.work / "extracted folder with spaces")
        self.assertEqual(executable.read_bytes(), self.binary.read_bytes())
        self.assertTrue(launcher.is_file())
        guide = executable.with_name("START-HERE.txt").read_text(encoding="utf-8")
        self.assertIn("0.5.0", guide)
        self.assertIn(self.platform, guide)
        self.assertTrue(executable.with_name("README.md").is_file())
        self.assertTrue(executable.with_name("CHANGELOG.md").is_file())
        for image in desktop_release.local_readme_images(desktop_release.ROOT / "README.md"):
            self.assertEqual((executable.parent / image).read_bytes(), (desktop_release.ROOT / image).read_bytes())
        if (desktop_release.ROOT / "roads_beneath_shadow/font_assets/LICENSE.txt").is_file():
            self.assertEqual(
                executable.with_name("FONT-LICENSE.txt").read_bytes(),
                (desktop_release.ROOT / "roads_beneath_shadow/font_assets/LICENSE.txt").read_bytes(),
            )
        self.assertEqual(executable.with_name("FONT-FALLBACK-LICENSE.txt").read_bytes(),
                         (desktop_release.ROOT / "roads_beneath_shadow/font_assets/FALLBACK-OFL.txt").read_bytes())
        if os.name != "nt":
            self.assertTrue(executable.stat().st_mode & 0o111)
            self.assertTrue(launcher.stat().st_mode & 0o111)

    def test_offline_guide_keeps_spaced_images_animation_and_skips_remote_badges(self):
        source = self.work / "offline guide source"
        (source / "assets").mkdir(parents=True)
        (source / "README.md").write_text(
            '[![Badge](https://example.test/badge.svg)](https://example.test/)\n'
            '![Menu](<assets/menu preview.png>)\n'
            '![Walk](assets/walk.gif "A walk along the road")\n', encoding="utf-8"
        )
        (source / "CHANGELOG.md").write_text("A portable player guide.\n", encoding="utf-8")
        (source / "Play Standalone.command").write_bytes((desktop_release.ROOT / "Play Standalone.command").read_bytes())
        (source / "assets/menu preview.png").write_bytes(b"native screenshot fixture")
        (source / "assets/walk.gif").write_bytes(b"animated demonstration fixture")
        with patch.object(desktop_release, "ROOT", source):
            archive = desktop_release.assemble_archive(self.binary, self.platform, "0.5.0", self.work / "offline downloads")
            executable, _launcher = desktop_release.extract_player_archive(archive, self.platform, self.work / "offline extraction")
        self.assertEqual((executable.parent / "assets/menu preview.png").read_bytes(), b"native screenshot fixture")
        self.assertEqual((executable.parent / "assets/walk.gif").read_bytes(), b"animated demonstration fixture")
        self.assertEqual(sorted(path.name for path in (executable.parent / "assets").iterdir()), ["menu preview.png", "walk.gif"])

    def test_missing_readme_image_rejects_an_otherwise_complete_archive(self):
        missing = self.work / "missing-guide-image.zip"
        with zipfile.ZipFile(missing, "w") as archive:
            files = {
                "Roads-Beneath-the-Shadow.exe": b"executable fixture",
                "Play Roads Beneath the Shadow.cmd": b"launcher fixture",
                "START-HERE.txt": b"Start the game",
                "README.md": b"![Gameplay](assets/missing.gif)\n",
                "CHANGELOG.md": b"Changes",
                "FONT-LICENSE.txt": b"Font license fixture",
                "FONT-FALLBACK-LICENSE.txt": b"Fallback font license fixture",
                "THIRD-PARTY-NOTICES.md": b"License fixture",
                "THIRD-PARTY-INVENTORY.json": json.dumps({"schema_version": 1, "payload": [{
                    "path": "_internal/shared-library.bin", "sha256": hashlib.sha256(b"Runtime fixture").hexdigest(),
                }]}).encode(),
                "_internal/shared-library.bin": b"Runtime fixture",
            }
            for name, data in files.items():
                archive.writestr(f"{desktop_release.GAME_NAME}/{name}", data)
        with self.assertRaisesRegex(ValueError, "README image is missing"):
            desktop_release.extract_player_archive(missing, "Windows-x64", self.work / "missing image extraction")

    def test_guide_image_cannot_read_a_file_outside_its_source_folder(self):
        source = self.work / "guide folder"
        source.mkdir()
        (self.work / "outside.png").write_bytes(b"outside the guide")
        (source / "README.md").write_text("![Preview](../outside.png)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must stay inside the player folder"):
            desktop_release.local_readme_images(source / "README.md")

    def test_incomplete_archive_does_not_pass_installation_qa(self):
        incomplete = self.work / "missing-binary.zip"
        with zipfile.ZipFile(incomplete, "w") as archive:
            archive.writestr(f"{desktop_release.GAME_NAME}/START-HERE.txt", "Extract first")
        with self.assertRaisesRegex(ValueError, "archive is incomplete"):
            desktop_release.extract_player_archive(incomplete, "Windows-x64", self.work / "incomplete")

    def test_archive_cannot_extract_files_outside_the_player_folder(self):
        invalid = self.work / "invalid.zip"
        with zipfile.ZipFile(invalid, "w") as archive:
            archive.writestr(f"{desktop_release.GAME_NAME}/../../outside.txt", "invalid")
        with self.assertRaisesRegex(ValueError, "Invalid player archive path"):
            desktop_release.extract_player_archive(invalid, "Windows-x64", self.work / "invalid extraction")
        self.assertFalse((self.work / "outside.txt").exists())

    def test_archive_retains_separate_runtime_and_detects_missing_library(self):
        executable, _ = desktop_release.extract_player_archive(self.archive, self.platform, self.work / "libraries")
        library = executable.parent / "_internal/shared-library.bin"
        self.assertEqual(library.read_bytes(), b"replaceable runtime library fixture")
        library.write_bytes(b"modified runtime")
        from scripts.third_party import verify_inventory
        with self.assertRaisesRegex(ValueError, "missing or altered runtime/source"):
            verify_inventory(executable.parent)

    def test_file_cli_checks_runtime_inventory_without_source_import_path(self):
        inventory = self.binary.parent / "THIRD-PARTY-INVENTORY.json"
        data = json.loads(inventory.read_text())
        data["payload"][0]["sha256"] = "0" * 64
        inventory.write_text(json.dumps(data))
        archive = desktop_release.assemble_archive(self.binary, self.platform, "0.5.0", self.work / "bad runtime downloads")
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([
            sys.executable, str(desktop_release.ROOT / "scripts/desktop_release.py"), "verify-archive",
            "--platform", self.platform, "--version", "0.5.0", "--archive", str(archive),
        ], cwd=self.work, env=environment, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or altered runtime/source", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    @unittest.skipIf(os.name == "nt", "PyInstaller's Unix library links are checked on Unix")
    def test_internal_library_links_are_archived_as_regular_replaceable_files(self):
        original = self.binary.parent / "_internal/shared-library.bin"
        link = original.with_name("shared-library-link.bin")
        link.symlink_to(original.name)
        third_party.materialize_internal_tree(self.binary.parent)
        inventory_path = self.binary.parent / third_party.INVENTORY_NAME
        inventory = json.loads(inventory_path.read_text())
        inventory["payload"], _ = third_party.collect_payload_inventory(self.binary.parent, {"components": []}, self.platform)
        inventory_path.write_text(json.dumps(inventory))
        archive = desktop_release.assemble_archive(self.binary, self.platform, "0.5.0", self.work / "linked downloads")
        executable, _ = desktop_release.extract_player_archive(archive, self.platform, self.work / "linked extraction")
        retained = executable.parent / "_internal" / link.name
        self.assertFalse(retained.is_symlink())
        self.assertEqual(retained.read_bytes(), original.read_bytes())

    @unittest.skipIf(os.name == "nt", "PyInstaller's Unix library links are checked on Unix")
    def test_assembly_refuses_to_copy_an_external_symlink_target(self):
        external = self.work / "outside the build.txt"
        external.write_text("This file is not part of the standalone build.\n")
        (self.binary.parent / "_internal" / "outside-link.txt").symlink_to(external)
        with self.assertRaisesRegex(ValueError, "build link leaves the standalone folder"):
            desktop_release.assemble_archive(self.binary, self.platform, "0.5.0", self.work / "external links")

    def test_png_header_without_image_data_cannot_pass_frozen_smoke(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, "Roads Beneath the Shadow 0.5.0\n", "")
            if "--check-runtime-assets" in args:
                decoded = {"images": 35, "world_maps": 13, "fonts": 4, "audio": 10, "metadata": 2,
                           "audio_driver": "dummy", "controller_backend": "pygame._sdl2.controller",
                           "font_fallbacks": desktop_release.expected_font_fallbacks()}
                return subprocess.CompletedProcess(args, 0, json.dumps(decoded) + "\n", "")
            if "--screenshot" in args:
                Path(args[args.index("--screenshot") + 1]).write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(args, 0, "May a star shine upon your road.", "")

        with patch.object(desktop_release.subprocess, "run", side_effect=run):
            with self.assertRaises((OSError, ValueError)):
                desktop_release.smoke_test(self.binary, expected_version="0.5.0")
        self.assertEqual(len(calls), 4)

    def test_stale_frozen_binary_is_rejected_before_packaging_new_version(self):
        with patch.object(
            desktop_release.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, "Roads Beneath the Shadow 0.4.0\n", ""),
        ) as run:
            with self.assertRaisesRegex(ValueError, "Frozen version mismatch"):
                desktop_release.smoke_test(self.binary, expected_version="0.5.0")
        self.assertEqual(run.call_count, 1)

    @unittest.skipIf(os.name == "nt", "Unix execute permissions are checked on Unix runners")
    def test_archive_missing_execute_bits_fails_before_launch(self):
        if self.platform == "Linux-x64":
            altered = self.work / "not-executable.tar.gz"
            with tarfile.open(self.archive, "r:gz") as source, tarfile.open(altered, "w:gz") as target:
                for member in source.getmembers():
                    if member.name.endswith("/" + desktop_release.GAME_NAME):
                        member.mode = 0o644
                    data = source.extractfile(member) if member.isfile() else None
                    target.addfile(member, data)
                    if data is not None:
                        data.close()
        else:
            altered = self.work / "not-executable.zip"
            with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(altered, "w") as target:
                for member in source.infolist():
                    if member.filename.endswith("/" + desktop_release.GAME_NAME):
                        member.external_attr = 0o100644 << 16
                    target.writestr(member, source.read(member))
        with self.assertRaisesRegex(ValueError, "lost execute permission"):
            desktop_release.extract_player_archive(altered, self.platform, self.work / "missing permissions")


@unittest.skipIf(os.name == "nt", "POSIX .command launchers are exercised on Unix runners")
class MacLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rbs source folder with spaces ")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.shell = shutil.which("zsh") or shutil.which("bash")
        if not self.shell:
            self.skipTest("No shell compatible with the .command launchers")
        tools = self.work / "tools"
        tools.mkdir()
        dirname = shutil.which("dirname")
        if not dirname:
            self.skipTest("dirname is unavailable")
        (tools / "dirname").symlink_to(dirname)
        self.record = self.work / "arguments.txt"
        self.environment = {**os.environ, "PATH": str(tools), "RBS_LAUNCH_TEST_RECORD": str(self.record)}

    def recorder(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$RBS_LAUNCH_TEST_RECORD"\n', encoding="utf-8")
        path.chmod(0o755)

    def test_source_launcher_uses_valid_local_venv_when_global_python_is_absent(self):
        self.recorder(self.work / ".venv/bin/python")
        launcher = self.work / "Play Roads Beneath the Shadow.command"
        shutil.copy2(desktop_release.ROOT / launcher.name, launcher)
        subprocess.run([self.shell, str(launcher), "--terminal", "--fast"], cwd=self.work.parent, env=self.environment, check=True, capture_output=True, timeout=10)
        recorded = self.record.read_text().splitlines()
        self.assertEqual(Path(recorded[0]).resolve(), self.work.resolve())
        self.assertEqual(recorded[1:], ["-m", "roads_beneath_shadow", "--terminal", "--fast"])

    def test_standalone_launcher_forwards_options_from_spaced_folder(self):
        self.recorder(self.work / desktop_release.GAME_NAME)
        launcher = self.work / "Play Roads Beneath the Shadow.command"
        shutil.copy2(desktop_release.ROOT / "Play Standalone.command", launcher)
        subprocess.run([self.shell, str(launcher), "--terminal", "--fast"], cwd=self.work.parent, env=self.environment, check=True, capture_output=True, timeout=10)
        recorded = self.record.read_text().splitlines()
        self.assertEqual(Path(recorded[0]).resolve(), self.work.resolve())
        self.assertEqual(recorded[1:], ["--terminal", "--fast"])


@unittest.skipUnless(os.name == "nt", "cmd launcher quoting is checked on Windows")
class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_command_preserves_spaced_paths_and_arguments(self):
        with tempfile.TemporaryDirectory(prefix="rbs batch folder with spaces ") as temporary:
            work = Path(temporary)
            script = work / "record arguments.py"
            script.write_text("import json,sys; print(json.dumps(sys.argv[1:]))", encoding="utf-8")
            launcher = work / "Play Roads Beneath the Shadow.cmd"
            launcher.write_bytes(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n'.encode())
            arguments = ["--screenshot", str(work / "screen with spaces.png"), "--check-install"]
            result = subprocess.run(desktop_release.launcher_command(launcher, "Windows-x64", arguments), capture_output=True, text=True, check=True, timeout=10)
            import json

            self.assertEqual(json.loads(result.stdout), arguments)


if __name__ == "__main__":
    unittest.main()
