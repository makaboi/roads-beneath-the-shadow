import os
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

from scripts import desktop_release


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
        self.binary = self.work / (desktop_release.GAME_NAME + (".exe" if os.name == "nt" else ""))
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
        if (desktop_release.ROOT / "roads_beneath_shadow/font_assets/LICENSE.txt").is_file():
            self.assertEqual(
                executable.with_name("FONT-LICENSE.txt").read_bytes(),
                (desktop_release.ROOT / "roads_beneath_shadow/font_assets/LICENSE.txt").read_bytes(),
            )
        if os.name != "nt":
            self.assertTrue(executable.stat().st_mode & 0o111)
            self.assertTrue(launcher.stat().st_mode & 0o111)

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

    def test_png_header_without_image_data_cannot_pass_frozen_smoke(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, "Roads Beneath the Shadow 0.5.0\n", "")
            if "--check-runtime-assets" in args:
                return subprocess.CompletedProcess(args, 0, '{"images":35,"world_maps":13,"fonts":2,"audio":10,"metadata":1,"audio_driver":"dummy"}\n', "")
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
