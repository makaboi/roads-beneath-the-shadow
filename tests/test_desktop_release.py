"""Exercise the release API semantics, including private drafts without tags."""

from copy import deepcopy
import builtins
import hashlib
import json
import io
from pathlib import Path
import subprocess
import tempfile
import tarfile
import zipfile
import unittest
from unittest.mock import patch

from scripts import desktop_release


VERSION = "0.4.0"
TAG = f"v{VERSION}"
COMMIT = "1" * 40
OLD_COMMIT = "2" * 40


class ReleaseServer:
    """GitHub-like fixture: a draft has an ID but no published tag lookup."""

    def __init__(self, downloads, *, existing=None, tag_commit=None, complete_upload=True):
        self.release = deepcopy(existing)
        self.downloads = downloads
        self.tag_commit = tag_commit
        self.complete_upload = complete_upload
        self.requests = []
        self.commands = []

    def api(self, path, *, missing_ok=False):
        self.requests.append(path)
        if path == f"releases/tags/{TAG}":
            # github_api translates an expected 404 into None.
            return deepcopy(self.release) if self.release and not self.release["draft"] else None
        if path.startswith("releases?per_page=100&page="):
            return [deepcopy(self.release)] if self.release else []
        if path == "releases/42":
            return deepcopy(self.release)
        if path == f"git/ref/tags/{TAG}":
            return {"object": {"type": "commit", "sha": self.tag_commit}} if self.tag_commit else None
        raise AssertionError(f"Unexpected GitHub API path: {path}")

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[2] == "create":
            self.release = {
                "id": 42, "tag_name": TAG, "draft": True,
                "target_commitish": args[args.index("--target") + 1], "assets": [],
            }
        elif args[2] == "edit" and "--target" in args:
            self.release["target_commitish"] = args[args.index("--target") + 1]
        elif args[2] == "upload":
            paths = self.downloads if self.complete_upload else self.downloads[:-1]
            self.release["assets"] = [
                {"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                 "digest": f"sha256:{desktop_release.archive_digest(path)}"}
                for path in paths
            ]
        elif args[2] == "edit" and "--draft=false" in args:
            self.release["draft"] = False
        else:
            raise AssertionError(f"Unexpected GitHub release command: {args}")
        return subprocess.CompletedProcess(args, 0)


class DesktopReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        for platform in desktop_release.PLATFORMS:
            archive = self.output / desktop_release.archive_name(platform)
            inventory = json.dumps({"schema_version": 1, "runtime": {"unresolved": []}}).encode()
            name = f"{desktop_release.GAME_NAME}/THIRD-PARTY-INVENTORY.json"
            if platform == "Linux-x64":
                with tarfile.open(archive, "w:gz") as target:
                    member = tarfile.TarInfo(name)
                    member.size = len(inventory)
                    target.addfile(member, io.BytesIO(inventory))
            else:
                with zipfile.ZipFile(archive, "w") as target:
                    target.writestr(name, inventory)
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_name(f"{archive.name}.sha256").write_text(
                f"{checksum}  {archive.name}\n", encoding="ascii"
            )
            archive.with_name(f"{archive.name}.qa.json").write_text(json.dumps({
                "platform": platform, "version": VERSION, "source_commit": COMMIT,
                "archive": {"sha256": checksum}, "third_party": {"unresolved": [], "inventory_sha256": hashlib.sha256(inventory).hexdigest()},
            }))
        self.downloads = desktop_release.verified_downloads(self.output)
        self.addCleanup(patch.stopall)
        # Version parsing itself is a Python 3.13 CI concern; these release and
        # checksum protocols also run in the game's Python 3.10 quality matrix.
        patch.object(desktop_release, "project_version", return_value=VERSION).start()
        patch.object(desktop_release, "github_commit", return_value=COMMIT).start()
        patch.object(desktop_release, "github_repository", return_value="fixture/game").start()
        self.quality_gate = patch.object(desktop_release, "verify_quality_gate", return_value={"run_id": 100, "verified_jobs": 8}).start()

    def publish(self, server):
        with patch.object(desktop_release, "github_api", side_effect=server.api), patch.object(
            desktop_release.subprocess, "run", side_effect=server.command
        ):
            desktop_release.publish_release(VERSION, self.output)

    @staticmethod
    def draft():
        return {"id": 42, "tag_name": TAG, "draft": True, "target_commitish": OLD_COMMIT, "assets": []}

    def test_draft_is_found_in_authenticated_list_when_tag_lookup_returns_404(self):
        server = ReleaseServer(self.downloads, existing=self.draft())
        with patch.object(desktop_release, "github_api", side_effect=server.api):
            found = desktop_release.release_for_tag(TAG)
        self.assertEqual(found["id"], 42)
        self.assertTrue(found["draft"])
        self.assertEqual(server.requests, [f"releases/tags/{TAG}", "releases?per_page=100&page=1"])

    def test_unresolved_native_notice_prevents_every_github_request(self):
        path = self.output / (desktop_release.archive_name("Windows-x64") + ".qa.json")
        report = json.loads(path.read_text())
        report["third_party"]["unresolved"] = [{"component": "compiler runtime", "reason": "Notice unavailable"}]
        path.write_text(json.dumps(report))
        server = ReleaseServer(self.downloads)
        with self.assertRaisesRegex(ValueError, "notices require review"):
            self.publish(server)
        self.assertEqual(server.requests, [])
        self.assertEqual(server.commands, [])

    def test_qa_report_for_another_archive_cannot_authorize_publication(self):
        path = self.output / (desktop_release.archive_name("Linux-x64") + ".qa.json")
        report = json.loads(path.read_text())
        report["archive"]["sha256"] = "f" * 64
        path.write_text(json.dumps(report))
        server = ReleaseServer(self.downloads)
        with self.assertRaisesRegex(ValueError, "exact archive/commit"):
            self.publish(server)
        self.assertEqual(server.requests, [])
        self.assertEqual(server.commands, [])

    def test_forged_inventory_hash_cannot_authorize_publication(self):
        path = self.output / (desktop_release.archive_name("Windows-x64") + ".qa.json")
        report = json.loads(path.read_text())
        report["third_party"]["inventory_sha256"] = "e" * 64
        path.write_text(json.dumps(report))
        server = ReleaseServer(self.downloads)
        with self.assertRaisesRegex(ValueError, "packaged third-party inventory"):
            self.publish(server)
        self.assertEqual(server.requests, [])
        self.assertEqual(server.commands, [])

    def test_changed_packaged_notice_result_cannot_be_hidden_by_empty_qa(self):
        archive = self.output / desktop_release.archive_name("Windows-x64")
        inventory = json.dumps({"schema_version": 1, "runtime": {"unresolved": [{"component": "missing native notice"}]}}).encode()
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr(f"{desktop_release.GAME_NAME}/THIRD-PARTY-INVENTORY.json", inventory)
        archive.with_name(archive.name + ".sha256").write_text(f"{desktop_release.archive_digest(archive)}  {archive.name}\n")
        path = archive.with_name(archive.name + ".qa.json")
        report = json.loads(path.read_text())
        report["archive"]["sha256"] = desktop_release.archive_digest(archive)
        report["third_party"]["inventory_sha256"] = hashlib.sha256(inventory).hexdigest()
        path.write_text(json.dumps(report))
        server = ReleaseServer(self.downloads)
        with self.assertRaisesRegex(ValueError, "notice results do not match"):
            self.publish(server)
        self.assertEqual(server.requests, [])
        self.assertEqual(server.commands, [])

    def test_draft_lookup_paginates_before_deciding_no_release_exists(self):
        first_page = [{"tag_name": f"other-{index}"} for index in range(100)]
        with patch.object(desktop_release, "github_api", side_effect=[None, first_page, [self.draft()]]) as api:
            self.assertEqual(desktop_release.release_for_tag(TAG)["id"], 42)
        self.assertEqual(api.call_args_list[-1].args[0], "releases?per_page=100&page=2")

    def test_missing_release_is_verified_by_id_before_and_after_upload(self):
        server = ReleaseServer(self.downloads)
        self.publish(server)
        self.assertEqual([command[2] for command in server.commands], ["create", "upload", "edit"])
        self.assertIn("--draft", server.commands[0])
        self.assertEqual(server.release["target_commitish"], COMMIT)
        self.assertFalse(server.release["draft"])
        self.assertEqual(len(server.release["assets"]), 8)
        self.assertEqual(server.requests.count("releases/42"), 2)
        first_id_lookup = server.requests.index("releases/42")
        self.assertNotIn(f"releases/tags/{TAG}", server.requests[first_id_lookup:])

    def test_failed_private_draft_is_reused_and_retargeted_to_rebuilt_commit(self):
        server = ReleaseServer(self.downloads, existing=self.draft())
        self.publish(server)
        self.assertEqual([command[2] for command in server.commands], ["edit", "upload", "edit"])
        retarget = server.commands[0]
        self.assertIn("--draft", retarget)
        self.assertEqual(retarget[retarget.index("--target") + 1], COMMIT)
        self.assertEqual(server.release["id"], 42)
        self.assertEqual(server.release["target_commitish"], COMMIT)
        self.assertFalse(server.release["draft"])

    def test_published_release_is_immutable_even_when_current_commit_differs(self):
        published = {**self.draft(), "draft": False}
        server = ReleaseServer(self.downloads, existing=published, tag_commit=OLD_COMMIT)
        self.publish(server)
        self.assertEqual(server.commands, [])
        self.assertEqual(server.release, published)
        self.assertEqual(server.requests, [f"releases/tags/{TAG}"])
        self.quality_gate.assert_not_called()

    def test_quality_failure_quarantines_complete_upload_before_publication(self):
        server = ReleaseServer(self.downloads)

        def failed_gate():
            self.assertTrue(server.release["draft"])
            self.assertEqual(len(server.release["assets"]), 8)
            raise ValueError("Quality Gate failed")

        self.quality_gate.side_effect = failed_gate
        with self.assertRaisesRegex(ValueError, "Quality Gate failed"):
            self.publish(server)
        self.assertTrue(server.release["draft"])
        self.assertEqual([command[2] for command in server.commands], ["create", "upload"])

    def test_tag_created_during_quality_wait_is_preserved_and_draft_stays_private(self):
        server = ReleaseServer(self.downloads)
        self.quality_gate.side_effect = lambda: setattr(server, "tag_commit", OLD_COMMIT)
        with self.assertRaisesRegex(ValueError, "already names another commit"):
            self.publish(server)
        self.assertEqual(server.tag_commit, OLD_COMMIT)
        self.assertTrue(server.release["draft"])
        self.assertEqual([command[2] for command in server.commands], ["create", "upload"])

    def test_stale_extra_download_keeps_recovered_draft_private(self):
        server = ReleaseServer(self.downloads, existing=self.draft())
        command = server.command

        def upload_with_stale_asset(args, **kwargs):
            result = command(args, **kwargs)
            if args[2] == "upload":
                server.release["assets"].append({"name": "outdated-mac-only.zip", "state": "uploaded", "size": 12})
            return result

        server.command = upload_with_stale_asset
        with self.assertRaisesRegex(ValueError, "unexpected downloads"):
            self.publish(server)
        self.assertTrue(server.release["draft"])
        self.assertFalse(any("--draft=false" in command for command in server.commands))

    def test_existing_tag_on_another_commit_prevents_draft_retarget_or_upload(self):
        server = ReleaseServer(self.downloads, existing=self.draft(), tag_commit=OLD_COMMIT)
        with self.assertRaisesRegex(ValueError, "already names another commit"):
            self.publish(server)
        self.assertEqual(server.commands, [])
        self.assertEqual(server.release["target_commitish"], OLD_COMMIT)

    def test_incomplete_server_upload_remains_private(self):
        server = ReleaseServer(self.downloads, complete_upload=False)
        with self.assertRaisesRegex(ValueError, "complete download"):
            self.publish(server)
        self.assertTrue(server.release["draft"])
        self.assertEqual([command[2] for command in server.commands], ["create", "upload"])

    def test_tampered_local_archive_prevents_all_github_requests(self):
        self.downloads[0].write_bytes(b"altered archive")
        server = ReleaseServer(self.downloads)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.publish(server)
        self.assertEqual(server.requests, [])
        self.assertEqual(server.commands, [])

    def test_wrong_server_digest_remains_private_even_when_name_and_size_match(self):
        server = ReleaseServer(self.downloads)
        original_api = server.api

        def corrupt_uploaded_digest(path, *, missing_ok=False):
            response = original_api(path, missing_ok=missing_ok)
            if path == "releases/42" and response["assets"]:
                response["assets"][0]["digest"] = "sha256:" + "0" * 64
            return response

        with patch.object(desktop_release, "github_api", side_effect=corrupt_uploaded_digest), patch.object(
            desktop_release.subprocess, "run", side_effect=server.command
        ):
            with self.assertRaisesRegex(ValueError, "GitHub download checksum mismatch"):
                desktop_release.publish_release(VERSION, self.output)
        self.assertTrue(server.release["draft"])
        self.assertEqual([command[2] for command in server.commands], ["create", "upload"])

    def test_expected_404_is_missing_but_other_api_failures_are_not(self):
        missing = subprocess.CompletedProcess([], 1, "", "gh: Not Found (HTTP 404)")
        with patch.object(desktop_release.subprocess, "run", return_value=missing):
            self.assertIsNone(desktop_release.github_api("releases/tags/absent", missing_ok=True))
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                desktop_release.github_api("releases/42")
        forbidden = subprocess.CompletedProcess([], 1, "", "gh: Forbidden (HTTP 403)")
        with patch.object(desktop_release.subprocess, "run", return_value=forbidden):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                desktop_release.github_api("releases/tags/absent", missing_ok=True)


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(desktop_release, "github_commit", return_value=COMMIT).start()
        self.sleep = patch.object(desktop_release, "sleep").start()

    @staticmethod
    def quality_run(**overrides):
        return {
            "id": 100, "run_attempt": 1, "head_sha": COMMIT, "head_branch": "main", "event": "push",
            "status": "completed", "conclusion": "success", "html_url": "https://github.com/fixture/game/actions/runs/100",
            **overrides,
        }

    @staticmethod
    def jobs():
        return [
            {"id": 300 + number, "run_attempt": 1, "name": name, "status": "completed", "conclusion": "success"}
            for number, name in enumerate(sorted(desktop_release.QUALITY_JOBS))
        ]

    def verify(self, responses, **kwargs):
        with patch.object(desktop_release, "github_api", side_effect=responses) as api:
            result = desktop_release.verify_quality_gate(**kwargs)
        return result, api

    def test_exact_commit_requires_all_eight_successful_matrix_jobs(self):
        result, api = self.verify([{"workflow_runs": [self.quality_run()]}, {"jobs": self.jobs()}])
        self.assertEqual(result, {"run_id": 100, "run_attempt": 1, "verified_jobs": 8})
        self.assertIn(f"head_sha={COMMIT}", api.call_args_list[0].args[0])
        self.assertEqual(api.call_args_list[1].args[0], "actions/runs/100/jobs?filter=all&per_page=100&page=1")
        self.sleep.assert_not_called()

    def test_queued_quality_work_waits_then_verifies_completed_attempt(self):
        pending = self.quality_run(status="in_progress", conclusion=None)
        result, _ = self.verify([
            {"workflow_runs": []}, {"workflow_runs": [pending]},
            {"workflow_runs": [self.quality_run(run_attempt=2)]}, {"jobs": self.jobs()},
        ])
        self.assertEqual(result["run_attempt"], 2)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertTrue(all(call.args[0] <= 10 for call in self.sleep.call_args_list))

    def test_newer_failed_run_cannot_reuse_an_older_success(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(ValueError, conclusion):
                self.verify([{"workflow_runs": [self.quality_run(), self.quality_run(id=101, conclusion=conclusion)]}])
        self.sleep.assert_not_called()

    def test_successful_workflow_without_python310_cell_cannot_publish(self):
        jobs = self.jobs()
        omitted = "windows-latest / Python 3.10"
        jobs = [job for job in jobs if job["name"] != omitted]
        with self.assertRaisesRegex(ValueError, omitted):
            self.verify([{"workflow_runs": [self.quality_run()]}, {"jobs": jobs}])

    def test_skipped_matrix_cell_is_not_a_successful_quality_gate(self):
        jobs = self.jobs()
        jobs[0]["conclusion"] = "skipped"
        with self.assertRaisesRegex(ValueError, "every required"):
            self.verify([{"workflow_runs": [self.quality_run()]}, {"jobs": jobs}])

    def test_rerun_failed_cell_can_use_untouched_successes_from_the_same_run(self):
        jobs = self.jobs()
        jobs[0]["conclusion"] = "failure"
        retry = {**jobs[0], "id": 1000, "run_attempt": 2, "conclusion": "success"}
        # Deliberately put the retry first: API ordering must not decide which
        # execution represents the latest result for this matrix cell.
        result, _ = self.verify([{"workflow_runs": [self.quality_run(run_attempt=2)]}, {"jobs": [retry, *jobs]}])
        self.assertEqual(result["verified_jobs"], 8)

    def test_latest_skipped_retry_cannot_reuse_that_cells_earlier_success(self):
        jobs = self.jobs()
        retry = {**jobs[0], "id": 1000, "run_attempt": 2, "conclusion": "skipped"}
        with self.assertRaisesRegex(ValueError, "every required"):
            self.verify([{"workflow_runs": [self.quality_run(run_attempt=2)]}, {"jobs": [retry, *jobs]}])

    def test_other_commit_branch_or_event_cannot_satisfy_gate_before_timeout(self):
        for overrides in ({"head_sha": OLD_COMMIT}, {"head_branch": "feature"}, {"event": "pull_request"}):
            with self.subTest(overrides=overrides), patch.object(desktop_release, "monotonic", side_effect=[100, 100, 101]):
                with self.assertRaisesRegex(TimeoutError, "remains private"):
                    self.verify([{"workflow_runs": [self.quality_run(**overrides)]}], timeout=1)
        self.sleep.assert_not_called()

    def test_network_request_is_bounded_by_the_remaining_gate_deadline(self):
        with patch.object(desktop_release, "monotonic", return_value=100), patch.object(
            desktop_release, "github_api", side_effect=subprocess.TimeoutExpired("gh api", 7)
        ) as api:
            with self.assertRaisesRegex(TimeoutError, "metadata did not respond"):
                desktop_release.verify_quality_gate(timeout=7)
        self.assertEqual(api.call_args.kwargs["timeout"], 7)
        self.sleep.assert_not_called()

    def test_invalid_api_payload_fails_without_claiming_quality_success(self):
        for responses in ([[]], [{"workflow_runs": [self.quality_run()]}, {"jobs": None}]):
            with self.subTest(responses=responses), self.assertRaisesRegex(ValueError, "invalid Quality Gate"):
                self.verify(responses)

    def test_matrix_jobs_are_found_on_later_pages(self):
        first_page = [{"name": f"Other check {number}", "status": "completed", "conclusion": "success"} for number in range(100)]
        _, api = self.verify([{"workflow_runs": [self.quality_run()]}, {"jobs": first_page}, {"jobs": self.jobs()}])
        self.assertTrue(api.call_args_list[-1].args[0].endswith("page=2"))


class ProjectVersionTests(unittest.TestCase):
    def test_python310_reader_uses_project_version_and_rejects_ambiguous_literals(self):
        original_import = builtins.__import__

        def without_tomllib(name, *args, **kwargs):
            if name == "tomllib":
                raise ModuleNotFoundError("Python 3.10 has no tomllib")
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary, patch("builtins.__import__", side_effect=without_tomllib):
            metadata = Path(temporary) / "pyproject.toml"
            metadata.write_text('[unrelated]\nversion="7.0.0"\n[project]\nversion = "0.5.0" # current release\n[tool.other]\nversion="2.0.0"\n')
            self.assertEqual(desktop_release.read_project_version(metadata), "0.5.0")
            for content in ('[project]\nversion="0.5.0"\nversion="0.6.0"\n', '[project]\nversion="0.5.0rc1"\n', '[project]\nname="the game"\n'):
                metadata.write_text(content)
                with self.assertRaises(ValueError):
                    desktop_release.read_project_version(metadata)


if __name__ == "__main__":
    unittest.main()
