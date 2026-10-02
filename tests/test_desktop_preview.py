"""Artifact-only dispatches stay read-only even for an already released version."""

import ast
import contextlib
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import desktop_release


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/desktop-release.yml"


def job_body(name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z]+:|\Z)", WORKFLOW.read_text(), re.M | re.S)
    if match is None:
        raise AssertionError(f"Missing workflow job: {name}")
    return match[1]


def job_enabled(name, *, ref="refs/heads/main", event="push", preview=False, build=True, publish=True):
    """Evaluate the actual, small boolean job guard using fixture contexts."""
    match = re.search(r"^    if: (.+)$", job_body(name), re.M)
    if match is None:
        raise AssertionError(f"Missing condition for job: {name}")
    expression = match[1]
    values = {
        "github.ref": ref,
        "github.event_name": event,
        "inputs.preview_only": preview,
        "needs.plan.outputs.build": str(build).lower(),
        "needs.plan.outputs.publish": str(publish).lower(),
    }
    for key, value in values.items():
        expression = expression.replace(key, repr(value))
    expression = expression.replace("&&", " and ").replace("||", " or ").replace("!", "not ")
    tree = ast.parse(expression.strip(), mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare, ast.Eq, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError("Unexpected expression in publication guard")
    return eval(compile(tree, str(WORKFLOW), "eval"), {"__builtins__": {}})


class DesktopPreviewTests(unittest.TestCase):
    def plan(self, *, preview=False, existing=None):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs.txt"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), patch.object(
                desktop_release, "project_version", return_value="0.4.0"
            ), patch.object(desktop_release, "release_for_tag", return_value=existing) as lookup, patch.object(
                desktop_release, "verify_existing_tag"
            ) as verify_tag, patch.object(desktop_release, "github_api") as api, patch.object(
                desktop_release.subprocess, "run"
            ) as command, contextlib.redirect_stdout(io.StringIO()):
                desktop_release.plan_release(preview_only=preview)
                values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            return values, lookup, verify_tag, api, command

    def test_preview_builds_existing_version_without_api_or_tag_operations(self):
        values, lookup, verify_tag, api, command = self.plan(preview=True, existing={"draft": False})
        self.assertEqual(values, {"version": "0.4.0", "tag": "v0.4.0", "build": "true", "publish": "false"})
        for operation in (lookup, verify_tag, api, command):
            operation.assert_not_called()

    def test_default_new_release_still_builds_and_publishes(self):
        values, lookup, verify_tag, _api, _command = self.plan()
        self.assertEqual((values["build"], values["publish"]), ("true", "true"))
        lookup.assert_called_once_with("v0.4.0")
        verify_tag.assert_called_once_with("v0.4.0")

    def test_published_release_still_skips_build_and_publication(self):
        values, _lookup, verify_tag, _api, _command = self.plan(existing={"draft": False})
        self.assertEqual((values["build"], values["publish"]), ("false", "false"))
        verify_tag.assert_not_called()

    def test_cli_preview_flag_selects_read_only_planning(self):
        with patch("sys.argv", ["desktop_release.py", "plan", "--preview-only"]), patch.object(
            desktop_release, "plan_release"
        ) as plan:
            desktop_release.main()
        plan.assert_called_once_with(preview_only=True)

    def test_preview_on_any_ref_builds_but_never_enables_publisher(self):
        for ref in ("refs/heads/codex/preview", "refs/heads/main", "refs/tags/v0.4.0"):
            with self.subTest(ref=ref):
                context = {"ref": ref, "event": "workflow_dispatch", "preview": True}
                self.assertTrue(job_enabled("plan", **context))
                self.assertTrue(job_enabled("build", **context))
                # Even a malformed planner output cannot publish a preview.
                self.assertFalse(job_enabled("publish", publish=True, **context))
                self.assertFalse(job_enabled("publish", publish=False, **context))

    def test_default_main_release_and_skip_conditions(self):
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertTrue(job_enabled("plan", event=event))
                self.assertTrue(job_enabled("build", event=event))
                self.assertTrue(job_enabled("publish", event=event))
                self.assertFalse(job_enabled("build", event=event, build=False))
                self.assertFalse(job_enabled("publish", event=event, publish=False))
        for event in ("push", "workflow_dispatch"):
            self.assertFalse(job_enabled("plan", ref="refs/heads/preview", event=event))
            self.assertFalse(job_enabled("publish", ref="refs/heads/preview", event=event))

    def test_pull_requests_including_forks_build_without_enabling_publisher(self):
        for ref in ("refs/pull/2/merge", "refs/pull/400/merge", "refs/heads/main"):
            with self.subTest(ref=ref):
                context = {"ref": ref, "event": "pull_request", "preview": False}
                self.assertTrue(job_enabled("plan", **context))
                self.assertTrue(job_enabled("build", **context))
                # The event guard rejects even a contradictory output from a fork.
                self.assertFalse(job_enabled("publish", publish=True, **context))
                self.assertFalse(job_enabled("publish", publish=False, **context))
        plan = job_body("plan")
        self.assertIn("github.event_name == 'pull_request'", plan)
        self.assertRegex(plan, r"run: python scripts/desktop_release.py plan\$\{\{ \(github.event_name == 'pull_request'.*' --preview-only'")
        self.assertRegex(WORKFLOW.read_text(), r"(?m)^permissions:\n  contents: read$")
        self.assertNotIn("pull_request_target", WORKFLOW.read_text())

    def test_all_four_native_builds_use_read_only_permissions_and_archive_qa(self):
        build = job_body("build")
        self.assertRegex(build, r"permissions:\n      contents: read")
        self.assertNotIn("contents: write", build)
        self.assertEqual(set(re.findall(r"platform: ([\w-]+)", build)), set(desktop_release.PLATFORMS))
        self.assertIn("scripts/check_installed_game.py", build)
        self.assertIn("scripts/desktop_release.py package", build)
        self.assertIn("--collect-data roads_beneath_shadow", build)
        self.assertIn("--onedir", build)
        self.assertNotIn("--onefile", build)
        self.assertIn("pygame-ce==2.5.8", build)
        self.assertIn("actions/upload-artifact@v4", build)


if __name__ == "__main__":
    unittest.main()
