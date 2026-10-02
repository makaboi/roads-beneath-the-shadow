"""Exercise the release API semantics, including private drafts without tags."""

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import tempfile
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
                {"name": path.name, "state": "uploaded", "size": path.stat().st_size}
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
            archive.write_bytes(f"Verified player archive for {platform}".encode())
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            archive.with_name(f"{archive.name}.sha256").write_text(
                f"{checksum}  {archive.name}\n", encoding="ascii"
            )
        self.downloads = desktop_release.verified_downloads(self.output)
        self.addCleanup(patch.stopall)
        # Version parsing itself is a Python 3.13 CI concern; these release and
        # checksum protocols also run in the game's Python 3.10 quality matrix.
        patch.object(desktop_release, "project_version", return_value=VERSION).start()
        patch.object(desktop_release, "github_commit", return_value=COMMIT).start()
        patch.object(desktop_release, "github_repository", return_value="fixture/game").start()

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


if __name__ == "__main__":
    unittest.main()
