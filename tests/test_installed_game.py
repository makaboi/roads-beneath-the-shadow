import hashlib
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import os
import sys
from unittest.mock import patch

from scripts import check_installed_game
from scripts.check_installed_game import source_manifest, validate_installation


class InstalledGameTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "source" / "roads_beneath_shadow"
        self.source.mkdir(parents=True)
        for name, content in {
            "__init__.py": b'"""The game."""\n',
            "pixel_world.py": b"WORLD_COUNT = 13\n",
            "pixel_assets/world-motion.png": b"character motion atlas",
            "audio_assets/ambient-buried.wav": b"buried hall soundscape",
            "font_assets/DejaVuSansMono.ttf": b"bundled font",
            "font_assets/LICENSE.txt": b"font license",
        }.items():
            path = self.source / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
        self.expected = source_manifest(self.source)
        self.installed = {
            "origin": str(Path(temporary.name) / "venv" / "site-packages" / "roads_beneath_shadow"),
            "version": "0.5.0", "runtime_version": "0.5.0", "files": dict(self.expected),
            "entrypoints": {check_installed_game.CONSOLE_COMMAND: check_installed_game.CONSOLE_TARGET},
        }

    def check(self):
        validate_installation(self.expected, self.installed, "0.5.0", source_package=self.source)

    def test_complete_regular_wheel_matches_source(self):
        self.check()
        self.assertEqual(len(self.expected), 6)

    def test_omitted_runtime_assets_and_font_license_fail(self):
        for name in ("font_assets/DejaVuSansMono.ttf", "font_assets/LICENSE.txt", "pixel_assets/world-motion.png", "audio_assets/ambient-buried.wav"):
            with self.subTest(name=name):
                self.installed["files"] = {key: value for key, value in self.expected.items() if key != name}
                with self.assertRaisesRegex(ValueError, "missing") as error:
                    self.check()
                self.assertIn(name, str(error.exception))

    def test_stale_installed_module_fails_even_if_remaining_files_match(self):
        self.installed["files"]["removed_scene.py"] = hashlib.sha256(b"old code").hexdigest()
        with self.assertRaisesRegex(ValueError, "stale files"):
            self.check()

    def test_same_named_corrupt_resource_fails(self):
        self.installed["files"]["pixel_assets/world-motion.png"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "different bytes"):
            self.check()

    def test_checkout_import_is_rejected_instead_of_claiming_installed_qa(self):
        self.installed["origin"] = str(self.source)
        with self.assertRaisesRegex(ValueError, "imported the checkout"):
            self.check()

    def test_installed_metadata_must_match_candidate_version(self):
        self.installed["version"] = "0.4.0"
        with self.assertRaisesRegex(ValueError, "does not match source version"):
            self.check()

    def test_runtime_version_must_match_distribution_metadata(self):
        self.installed["runtime_version"] = "0.4.0"
        with self.assertRaisesRegex(ValueError, "Runtime version"):
            self.check()

    def test_documented_console_command_must_have_the_correct_entry_point(self):
        for entries in ({}, {check_installed_game.CONSOLE_COMMAND: "old_game:main"}):
            with self.subTest(entries=entries):
                self.installed["entrypoints"] = entries
                with self.assertRaisesRegex(ValueError, "wrong entry point"):
                    self.check()

    def test_source_manifest_ignores_interpreter_caches_and_hidden_work_files(self):
        cache = self.source / "__pycache__"
        cache.mkdir()
        (cache / "pixel_world.cpython-313.pyc").write_bytes(b"bytecode")
        (self.source / "font_assets" / ".download-temp").write_bytes(b"unfinished")
        self.assertEqual(source_manifest(self.source), self.expected)

    @unittest.skipIf(os.name == "nt", "Windows venv executables are copies rather than Unix symlinks")
    def test_cli_preserves_virtualenv_interpreter_symlink(self):
        interpreter = self.source.parent / "venv" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)
        report = {"version": "0.5.0", "verified_files": 6}
        with patch.object(sys, "argv", ["check_installed_game.py", "--python", str(interpreter)]), patch.object(
            check_installed_game, "check_installation", return_value=report
        ) as check:
            check_installed_game.main()
        self.assertEqual(check.call_args.args[0], interpreter.absolute())
        self.assertNotEqual(check.call_args.args[0], interpreter.resolve())


class VersionCommandTests(unittest.TestCase):
    def test_version_parser_reports_runtime_version_and_exits_successfully(self):
        from roads_beneath_shadow import __main__ as entrypoint

        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit:
            entrypoint.build_parser().parse_args(["--version"])
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(output.getvalue(), f"Roads Beneath the Shadow {entrypoint.__version__}\n")

    def test_version_runtime_does_not_initialize_settings_profiles_or_game(self):
        from roads_beneath_shadow import __main__ as entrypoint

        with patch.object(sys, "argv", ["roads-beneath-shadow", "--version"]), contextlib.redirect_stdout(io.StringIO()):
            with patch.object(entrypoint, "SettingsManager") as settings, patch.object(
                entrypoint, "ProfileManager"
            ) as profiles, patch.object(entrypoint, "Game") as game, self.assertRaises(SystemExit) as exit:
                entrypoint.main()
        self.assertEqual(exit.exception.code, 0)
        settings.assert_not_called()
        profiles.assert_not_called()
        game.assert_not_called()


if __name__ == "__main__":
    unittest.main()
