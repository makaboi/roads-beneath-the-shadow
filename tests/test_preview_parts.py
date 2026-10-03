"""Verify exact-byte preview review parts and their publication boundary."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_preview_parts as review


COMMIT = "1" * 40


class PreviewPartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rbs preview parts Éowen ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "native downloads"
        self.input.mkdir()
        self.output = self.root / "independent review"
        self.environment = patch.dict(os.environ, {"GITHUB_SHA": COMMIT})
        self.environment.start(); self.addCleanup(self.environment.stop)

    def fixture(self, payload=b"exact native preview bytes", platform="Linux-x64"):
        archive = self.input / review.archive_name(platform)
        archive.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        report = {"platform": platform, "version": "0.7.0", "source_commit": COMMIT,
                  "archive": {"name": archive.name, "size_bytes": len(payload), "sha256": digest}}
        qa = archive.with_name(archive.name + ".qa.json")
        qa.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return archive, qa

    def test_round_trip_preserves_every_byte_and_hash_for_all_platform_names(self):
        for platform in review.PLATFORMS:
            with self.subTest(platform=platform):
                payload = bytes(range(31))
                archive, qa = self.fixture(payload, platform)
                output = self.output / platform
                manifest = review.prepare_preview_parts(self.input, output, platform, part_bytes=10)
                self.assertEqual(manifest["source_commit"], COMMIT)
                self.assertEqual(manifest["platform"], platform)
                self.assertEqual(manifest["version"], "0.7.0")
                self.assertEqual([p["size_bytes"] for p in manifest["parts"]], [10, 10, 10, 1])
                self.assertEqual([p["offset"] for p in manifest["parts"]], [0, 10, 20, 30])
                combined = bytearray()
                for part in manifest["parts"]:
                    folder = output / f"part-{part['number']:03d}"
                    data = (folder / part["name"]).read_bytes()
                    self.assertEqual(len(data), part["size_bytes"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), part["sha256"])
                    self.assertEqual(json.loads((folder / review.MANIFEST_NAME).read_bytes()), manifest)
                    self.assertEqual((folder / qa.name).read_bytes(), qa.read_bytes())
                    combined.extend(data)
                self.assertEqual(combined, payload)
                self.assertEqual(hashlib.sha256(combined).hexdigest(), manifest["archive"]["sha256"])

    def test_exact_boundary_has_no_empty_trailing_part(self):
        self.fixture(b"x" * 12)
        manifest = review.prepare_preview_parts(self.input, self.output, "Linux-x64", part_bytes=6)
        self.assertEqual([p["size_bytes"] for p in manifest["parts"]], [6, 6])
        self.assertFalse((self.output / "part-003").exists())

    def test_windows_crlf_checksum_is_valid_and_retained_byte_for_byte(self):
        archive, _ = self.fixture(platform="Windows-x64")
        checksum = archive.with_name(archive.name + ".sha256")
        original = checksum.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        checksum.write_bytes(original)
        manifest = review.prepare_preview_parts(self.input, self.output, "Windows-x64", part_bytes=10)
        self.assertEqual(manifest["checksum_sha256"], hashlib.sha256(original).hexdigest())
        for part in manifest["parts"]:
            folder = self.output / f"part-{part['number']:03d}"
            self.assertEqual((folder / checksum.name).read_bytes(), original)

    def test_changed_archive_bytes_never_receive_a_valid_manifest(self):
        archive, _ = self.fixture()
        archive.write_bytes(b"X" + archive.read_bytes()[1:])
        with self.assertRaisesRegex(ValueError, "bytes do not match"):
            review.prepare_preview_parts(self.input, self.output, "Linux-x64", part_bytes=10)
        self.assertEqual(list(self.output.rglob(review.MANIFEST_NAME)), [])

    def test_existing_evidence_is_preserved(self):
        self.fixture()
        self.output.mkdir()
        retained = self.output / review.MANIFEST_NAME
        retained.write_bytes(b"previous evidence")
        with self.assertRaises(FileExistsError):
            review.prepare_preview_parts(self.input, self.output, "Linux-x64", part_bytes=10)
        self.assertEqual(retained.read_bytes(), b"previous evidence")

    def test_source_commit_and_archive_metadata_must_match(self):
        _, qa = self.fixture()
        original = json.loads(qa.read_bytes())
        mutations = ({"source_commit": "2" * 40}, {"platform": "Windows-x64"}, {"version": "latest"},
                     {"archive": {**original["archive"], "size_bytes": True}},
                     {"archive": {**original["archive"], "name": "another.zip"}},
                     {"archive": {**original["archive"], "sha256": "0" * 64}})
        for index, change in enumerate(mutations):
            with self.subTest(change=change):
                qa.write_text(json.dumps({**original, **change}))
                output = self.root / f"invalid-{index}"
                with self.assertRaisesRegex(ValueError, "exact archive/platform/version/source commit"):
                    review.prepare_preview_parts(self.input, output, "Linux-x64", part_bytes=10)
                self.assertFalse(output.exists())

    def test_sizes_are_bounded_and_oversized_metadata_is_rejected(self):
        _, qa = self.fixture(b"x" * 41)
        with self.assertRaisesRegex(ValueError, "at most four"):
            review.prepare_preview_parts(self.input, self.output, "Linux-x64", part_bytes=10)
        for size in (0, -1, True, review.PART_BYTES + 1):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "review-part size"):
                review.prepare_preview_parts(self.input, self.output, "Linux-x64", part_bytes=size)
        self.fixture(b"x")
        qa.write_bytes(b"x" * (review.METADATA_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "bounded size"):
            review.prepare_preview_parts(self.input, self.output, "Linux-x64")
        self.assertFalse(self.output.exists())

    def test_malformed_qa_objects_and_wrong_planned_version_are_rejected(self):
        _, qa = self.fixture()
        original = json.loads(qa.read_bytes())
        for index, value in enumerate(([], None, {**original, "archive": []}, {**original, "archive": None})):
            with self.subTest(value=value):
                qa.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, "must be objects"):
                    review.prepare_preview_parts(self.input, self.root / f"malformed-{index}", "Linux-x64")
        qa.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "exact archive/platform/version/source commit"):
            review.prepare_preview_parts(self.input, self.output, "Linux-x64", expected_version="0.7.1")
        self.assertFalse(self.output.exists())

    def test_review_uploads_are_separate_from_original_desktop_publication(self):
        workflow = (review.Path(__file__).resolve().parents[1] / ".github/workflows/desktop-release.yml").read_text()
        self.assertEqual(workflow.count("name: desktop-${{ matrix.platform }}"), 1)
        self.assertIn("pattern: desktop-*\n", workflow)
        for number in range(1, review.MAX_PARTS + 1):
            self.assertIn(f"name: review-desktop-${{{{ matrix.platform }}}}-part-{number}", workflow)
            self.assertIn(f"path: preview-inspection-parts/part-{number:03d}/*", workflow)
        self.assertEqual(workflow.count("retention-days: 14"), review.MAX_PARTS)
        self.assertLess(review.PART_BYTES + 3 * review.METADATA_BYTES, 24 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
