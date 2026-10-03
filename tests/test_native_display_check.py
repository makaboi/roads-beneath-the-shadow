"""Native-check ownership and CI contracts, without starting a display server."""

import argparse
import ast
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import check_native_display as native


WORKFLOW = native.ROOT / ".github" / "workflows" / "quality.yml"


def step_body(name):
    match = re.search(r"^      - name: " + re.escape(name) + r"\n(.*?)(?=^      - |\Z)",
                      WORKFLOW.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError("Missing native display workflow step: " + name)
    return match[1]


def step_enabled(name, system, python, always=True):
    match = re.search(r"^        if: (.+)$", step_body(name), re.MULTILINE)
    if match is None:
        raise AssertionError("Missing native-check matrix guard")
    expression = match[1].replace("matrix.os", repr(system)).replace("matrix.python", repr(python))
    expression = expression.replace("always()", repr(always)).replace("&&", " and ")
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Compare, ast.Eq, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError("Unexpected native-check guard expression")
    return eval(compile(tree, str(WORKFLOW), "eval"), {"__builtins__": {}})


class NativeDisplayHelperTests(unittest.TestCase):
    def test_cold_start_readiness_has_time_to_arrive_but_keeps_the_owner_deadline(self):
        with tempfile.TemporaryDirectory(prefix="rbs native delayed readiness ") as temporary:
            output = Path(temporary)
            player = SimpleNamespace(pid=12345, poll=lambda: None)
            state = {"probe_pid": player.pid, "owner_pid": os.getpid(), "ready": False}
            native.write_json(output / "probe-startup.json", {
                "probe_pid": player.pid, "owner_pid": os.getpid(), "phase": "source_imports_loaded",
            })

            def wait(timeout, deadline=50):
                clock = [0.0]
                native.write_json(output / "probe-progress.json", state)

                def delayed_start(_seconds):
                    clock[0] = 6.0
                    native.write_json(output / "probe-progress.json", {**state, "ready": True})

                with patch.object(native.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
                    native.time, "sleep", side_effect=delayed_start
                ):
                    return native.wait_probe_progress(player, Mock(), output, deadline,
                                                      lambda value: value["ready"], timeout=timeout)

            with self.assertRaisesRegex(TimeoutError, "last startup phase: source_imports_loaded"):
                wait(5)
            self.assertTrue(wait(native.STARTUP_TIMEOUT)["ready"])
            with self.assertRaises(TimeoutError):
                wait(native.STARTUP_TIMEOUT, deadline=3)

    def test_startup_wait_rejects_a_foreign_phase_and_an_exited_probe(self):
        with tempfile.TemporaryDirectory(prefix="rbs native startup identity ") as temporary:
            output = Path(temporary)
            player = SimpleNamespace(pid=12345, poll=lambda: None)
            native.write_json(output / "probe-startup.json", {
                "probe_pid": 54321, "owner_pid": os.getpid(), "phase": "first_frame_rendered",
            })
            with self.assertRaisesRegex(RuntimeError, "startup belongs to another probe/owner"):
                native.wait_probe_progress(player, Mock(), output, time.monotonic() + 1,
                                           lambda value: True, timeout=native.STARTUP_TIMEOUT)
            player.poll = lambda: 1
            with self.assertRaisesRegex(RuntimeError, "probe exited before completing checks"):
                native.wait_probe_progress(player, Mock(), output, time.monotonic() + 1,
                                           lambda value: True, timeout=native.STARTUP_TIMEOUT)

    def test_timeout_has_a_small_explicit_upper_bound(self):
        self.assertEqual(native.check_timeout(15), 15)
        self.assertEqual(native.check_timeout(90), 90)
        for value in (-1, 0, 14.9, 90.1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                native.check_timeout(value)

    def test_tool_discovery_uses_standard_names_and_optional_path(self):
        paths = []

        def which(name, *, path):
            paths.append((name, path))
            return "/tools with spaces/" + name

        with patch.dict(os.environ, {"PATH": "/existing/tools"}), patch.object(native.shutil, "which", side_effect=which):
            found, environment = native.find_tools("/local tools/bin", "openbox")
        self.assertEqual(set(found), {"Xvfb", "xdotool", "xprop", "openbox"})
        self.assertEqual(environment["PATH"], "/local tools/bin" + os.pathsep + "/existing/tools")
        self.assertTrue(all(path == environment["PATH"] for _, path in paths))

    def test_missing_tools_produce_a_failure_report_before_any_process_launch(self):
        with tempfile.TemporaryDirectory(prefix="rbs native missing tools ") as temporary:
            output = Path(temporary) / "Éowen report"
            with patch.object(native.sys, "platform", "linux"), patch.object(native.shutil, "which", return_value=None), patch.object(
                native, "OwnedProcesses"
            ) as owner:
                report = native.check_native_display(output)
            owner.assert_not_called()
            self.assertEqual(report["status"], "failed")
            self.assertIn("Install native display tools first", report["errors"][0])
            self.assertEqual(json.loads((output / "native-display-report.json").read_text()), report)
            self.assertTrue((output / "owner-error.log").is_file())

    def test_spaced_unicode_report_is_atomically_replaced(self):
        with tempfile.TemporaryDirectory(prefix="rbs native report ") as temporary:
            path = Path(temporary) / "Éowen review.json"
            native.write_json(path, {"entry": "Éowen", "frame": 1})
            native.write_json(path, {"entry": "éowen", "frame": 2})
            self.assertEqual(json.loads(path.read_text()), {"entry": "éowen", "frame": 2})
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_existing_output_and_control_files_are_preserved_without_launch(self):
        with tempfile.TemporaryDirectory(prefix="rbs native existing evidence ") as temporary:
            output = Path(temporary)
            control = output / "control.json"
            control.write_text('{"operation":"quit"}')
            with patch.object(native, "OwnedProcesses") as owner, self.assertRaises(FileExistsError):
                native.check_native_display(output)
            owner.assert_not_called()
            self.assertEqual(control.read_text(), '{"operation":"quit"}')


@unittest.skipUnless(sys.platform.startswith("linux"), "Owned display descendants use Linux subreaper support")
class NativeDisplayOwnershipTests(unittest.TestCase):
    def wait_file(self, path):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not path.is_file():
            time.sleep(0.01)
        self.assertTrue(path.is_file(), "Owned child did not start its descendant")

    def test_cleanup_reaps_owned_descendant_and_preserves_unrelated_process(self):
        with tempfile.TemporaryDirectory(prefix="rbs native owned children ") as temporary:
            output = Path(temporary)
            foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
            owner = native.OwnedProcesses(output)
            try:
                pid_file = output / "descendant.pid"
                code = (
                    "import subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    "open(sys.argv[1],'w').write(str(child.pid)); time.sleep(30)"
                )
                direct = owner.launch("owned-fixture", [sys.executable, "-c", code, str(pid_file)], dict(os.environ))
                self.wait_file(pid_file)
                descendant = int(pid_file.read_text())
                cleanup = owner.close()
                self.assertEqual(cleanup["errors"], [])
                self.assertTrue(cleanup["all_owned_pids_absent"])
                self.assertFalse(Path(f"/proc/{direct.pid}").exists())
                self.assertFalse(Path(f"/proc/{descendant}").exists())
                self.assertEqual({entry["pid"] for entry in cleanup["adopted_reaps"]}, {descendant})
                self.assertNotIn(foreign.pid, cleanup["observed_owned_pids"])
                self.assertIsNone(foreign.poll(), "Native cleanup signalled an unrelated process")
                self.assertIs(owner.close(), cleanup)
            finally:
                owner.close()
                foreign.terminate()
                foreign.wait(timeout=3)

    def test_startup_failure_waits_already_launched_server_and_keeps_raw_log(self):
        with tempfile.TemporaryDirectory(prefix="rbs native failed startup ") as temporary:
            output = Path(temporary) / "failed-startup"
            launched = []
            original_launch = native.OwnedProcesses.launch

            def launch_fixture(owner, role, arguments, environment, **keywords):
                process = original_launch(owner, role, [sys.executable, "-c", "import time; time.sleep(30)"], environment)
                launched.append(process)
                return process

            found = {name: "/unused/" + name for name in ("Xvfb", "xdotool", "xprop", "openbox")}
            with patch.object(native, "find_tools", return_value=(found, dict(os.environ))), patch.object(
                native.OwnedProcesses, "launch", launch_fixture
            ), patch.object(native, "display_number", side_effect=RuntimeError("injected server startup failure")):
                report = native.check_native_display(output)
            self.assertEqual(report["status"], "failed")
            self.assertIn("injected server startup failure", report["errors"][0])
            self.assertEqual(len(launched), 1)
            self.assertIsNotNone(launched[0].returncode)
            self.assertFalse(Path(f"/proc/{launched[0].pid}").exists())
            self.assertTrue(report["cleanup"]["all_owned_pids_absent"])
            self.assertEqual(report["cleanup"]["errors"], [])
            self.assertIn("xvfb.log", report["logs"])

    def test_dedicated_owner_reaps_detached_child_after_abrupt_parent_exit(self):
        # The fresh fixture is the sole subreaper owner. An unrelated process
        # belongs to this outer unittest process, not the dedicated fixture.
        with tempfile.TemporaryDirectory(prefix="rbs detached native children ") as temporary:
            output = Path(temporary)
            foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
            try:
                fixture = (
                    "import json,os,sys,time; from pathlib import Path; "
                    "sys.path.insert(0,sys.argv[1]); from scripts.check_native_display import OwnedProcesses; "
                    "base=Path(sys.argv[2]); owner=OwnedProcesses(base,dedicated_owner=True); "
                    "code=\"import subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True); open(sys.argv[1],'w').write(str(child.pid))\"; "
                    "parent=owner.launch('detached-fixture',[sys.executable,'-c',code,str(base/'detached.pid')],dict(os.environ)); "
                    "parent.wait(timeout=3); cleanup=owner.close(); "
                    "(base/'cleanup.json').write_text(json.dumps(cleanup)); "
                    "sys.exit(0 if cleanup['all_owned_pids_absent'] and not cleanup['errors'] else 1)"
                )
                completed = subprocess.run([sys.executable, "-c", fixture, str(native.ROOT), str(output)],
                                           capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                cleanup = json.loads((output / "cleanup.json").read_text())
                detached = int((output / "detached.pid").read_text())
                self.assertEqual({item["pid"] for item in cleanup["adopted_reaps"]}, {detached})
                self.assertFalse(Path(f"/proc/{detached}").exists())
                self.assertNotIn(foreign.pid, cleanup["observed_owned_pids"])
                self.assertIsNone(foreign.poll())
            finally:
                foreign.terminate()
                foreign.wait(timeout=3)

    def test_library_owner_reports_ambiguous_adoption_without_signalling_it(self):
        with tempfile.TemporaryDirectory(prefix="rbs guarded detached caller ") as temporary:
            output = Path(temporary)
            owner = native.OwnedProcesses(output)
            detached = None
            try:
                code = (
                    "import subprocess,sys; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True); "
                    "open(sys.argv[1],'w').write(str(child.pid))"
                )
                parent = owner.launch("ambiguous-fixture", [sys.executable, "-c", code, str(output / "detached.pid")], dict(os.environ))
                parent.wait(timeout=3)
                detached = int((output / "detached.pid").read_text())
                cleanup = owner.close()
                self.assertFalse(cleanup["all_owned_pids_absent"])
                self.assertEqual(cleanup["ambiguous_adopted_pids"], [detached])
                self.assertTrue(Path(f"/proc/{detached}").exists())
                self.assertIn("were preserved, not signalled", cleanup["errors"][0])
            finally:
                owner.close()
                if detached is not None:
                    try:
                        os.kill(detached, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    os.waitpid(detached, 0)


class NativeDisplayWorkflowTests(unittest.TestCase):
    def test_exactly_one_of_eight_matrix_cells_runs_native_display_check(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        systems = [item.strip() for item in re.search(r"^        os: \[([^\]]+)\]$", workflow, re.MULTILINE)[1].split(",")]
        versions = ast.literal_eval(re.search(r"^        python: (.+)$", workflow, re.MULTILINE)[1])
        self.assertEqual(len(systems) * len(versions), 8)
        for name in ("Install Linux native display tools", "Check real X11 resize and fullscreen lifecycle", "Retain native display report and raw logs"):
            enabled = [(system, version) for system in systems for version in versions if step_enabled(name, system, version)]
            self.assertEqual(enabled, [("ubuntu-latest", "3.13")])

    def test_failure_artifact_is_retained_and_check_has_bounded_runtime(self):
        artifact = step_body("Retain native display report and raw logs")
        self.assertIn("if: always()", artifact)
        self.assertIn("actions/upload-artifact@v4", artifact)
        self.assertIn("native-display-check/", artifact)
        self.assertTrue(step_enabled("Retain native display report and raw logs", "ubuntu-latest", "3.13", always=True))
        self.assertFalse(step_enabled("Retain native display report and raw logs", "windows-latest", "3.13", always=True))
        check = step_body("Check real X11 resize and fullscreen lifecycle")
        self.assertIn("timeout-minutes: 3", check)
        self.assertIn("--timeout 90", check)
        self.assertIn('"${{ runner.temp }}/native-display-check"', check)
        install = step_body("Install Linux native display tools")
        self.assertIn("--no-install-recommends", install)
        for name in ("xvfb", "openbox", "xdotool", "x11-utils"):
            self.assertIn(name, install)
        self.assertNotIn("contents: write", WORKFLOW.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
