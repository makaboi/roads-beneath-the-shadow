"""Player packages retain verified library sources and auditable notices."""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest
import zipfile
from unittest.mock import patch

from scripts import third_party
from scripts import runtime_notices
from scripts import desktop_release


class MaterializedPayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "_internal").mkdir(parents=True)

    def link(self, path, target, *, directory=False):
        try:
            path.symlink_to(Path(target), target_is_directory=directory)
        except OSError:
            self.skipTest("Symbolic links are unavailable")

    def framework(self):
        framework = self.bundle / "_internal/Python.framework"
        version = framework / "Versions/3.13"
        (version / "Resources").mkdir(parents=True)
        (version / "Python").write_bytes(b"retained Python runtime")
        (version / "Resources/Info.plist").write_bytes(b"retained CPython metadata")
        self.link(framework / "Versions/Current", "3.13", directory=True)
        self.link(framework / "Resources", "Versions/Current/Resources", directory=True)
        self.link(framework / "Python", "Versions/Current/Python")
        self.link(self.bundle / "_internal/Python", "Python.framework/Python")
        return {
            "_internal/Python": b"retained Python runtime",
            "_internal/Python.framework/Python": b"retained Python runtime",
            "_internal/Python.framework/Versions/3.13/Python": b"retained Python runtime",
            "_internal/Python.framework/Versions/Current/Python": b"retained Python runtime",
            "_internal/Python.framework/Resources/Info.plist": b"retained CPython metadata",
            "_internal/Python.framework/Versions/3.13/Resources/Info.plist": b"retained CPython metadata",
            "_internal/Python.framework/Versions/Current/Resources/Info.plist": b"retained CPython metadata",
        }

    def record_inventory(self):
        payload, _ = third_party.collect_payload_inventory(self.bundle, {"components": []}, "macOS-Intel")
        sources, supporting = [], []
        third = self.bundle / "third-party"
        for path in sorted(third.rglob("*")):
            if not path.is_file():
                continue
            record = {"path": path.relative_to(self.bundle).as_posix(), "sha256": third_party.digest(path)}
            (sources if record["path"].startswith("third-party/sources/") else supporting).append(record)
        inventory = {"schema_version": 1, "payload": payload, "source_archives": sources, "supporting_files": supporting}
        (self.bundle / third_party.INVENTORY_NAME).write_text(json.dumps(inventory))
        return inventory

    def test_framework_directory_aliases_are_inventoried_and_retained_exactly(self):
        expected = self.framework()
        third_party.materialize_internal_tree(self.bundle)
        inventory = self.record_inventory()
        self.assertEqual({item["path"] for item in inventory["payload"]}, set(expected))
        for item in inventory["payload"]:
            path = self.bundle / item["path"]
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), expected[item["path"]])
            self.assertEqual(item["size_bytes"], len(expected[item["path"]]))
        inventory_bytes = (self.bundle / third_party.INVENTORY_NAME).read_bytes()
        (self.bundle / third_party.NOTICES_NAME).write_text("Retained CPython notices")
        platform = "Windows-x64" if os.name == "nt" else "macOS-Intel"
        executable = self.bundle / (desktop_release.GAME_NAME + (".exe" if os.name == "nt" else ""))
        executable.write_bytes(b"fixture executable")
        archive = desktop_release.assemble_archive(executable, platform, "0.6.1", self.root / "downloads")
        with zipfile.ZipFile(archive) as retained:
            prefix = desktop_release.GAME_NAME + "/"
            self.assertEqual(retained.read(prefix + third_party.INVENTORY_NAME), inventory_bytes)
            actual = {member.filename[len(prefix):] for member in retained.infolist()
                      if member.filename.startswith(prefix + "_internal/") and not member.is_dir()}
            self.assertEqual(actual, set(expected))
            for path, data in expected.items():
                self.assertEqual(retained.read(prefix + path), data)
        extracted, _ = desktop_release.extract_player_archive(archive, platform, self.root / "extracted")
        self.assertEqual(third_party.verify_inventory(extracted.parent), inventory)

    def test_collection_rejects_unmaterialized_framework_aliases(self):
        self.framework()
        with self.assertRaisesRegex(ValueError, "without symbolic links"):
            third_party.collect_payload_inventory(self.bundle, {"components": []}, "macOS-Intel")

    def test_unlisted_runtime_source_and_notice_files_are_rejected(self):
        payload = self.bundle / "_internal/declared"
        payload.write_bytes(b"declared runtime")
        self.record_inventory()
        for name in ("_internal/extra", "third-party/sources/extra.tar.gz", "third-party/runtime/extra-LICENSE.txt"):
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not authorized by the inventory")
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, "unlisted files"):
                third_party.verify_inventory(self.bundle)
            path.unlink()

    def test_same_size_runtime_source_and_notice_mutations_are_rejected(self):
        names = ("_internal/runtime", "third-party/sources/source.tar.gz", "third-party/runtime/LICENSE.txt")
        for name in names:
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original")
        self.record_inventory()
        for name in names:
            path = self.bundle / name
            path.write_bytes(b"modified")
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, "missing or altered"):
                third_party.verify_inventory(self.bundle)
            path.write_bytes(b"original")

    def test_source_and_supporting_records_cannot_swap_groups(self):
        for name in ("third-party/sources/source.tar.gz", "third-party/runtime/LICENSE.txt"):
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"retained bytes")
        inventory = self.record_inventory()
        inventory["source_archives"], inventory["supporting_files"] = inventory["supporting_files"], inventory["source_archives"]
        (self.bundle / third_party.INVENTORY_NAME).write_text(json.dumps(inventory))
        with self.assertRaisesRegex(ValueError, "outside the retained sources group"):
            third_party.verify_inventory(self.bundle)

    def test_materialization_rejects_a_nested_external_link_before_copying(self):
        contained = self.bundle / "reference"
        contained.mkdir()
        external = self.root / "external"
        external.write_bytes(b"external bytes must remain")
        self.link(contained / "outside", external)
        self.link(self.bundle / "_internal/alias", contained, directory=True)
        with self.assertRaisesRegex(ValueError, "leaves the standalone folder"):
            third_party.materialize_internal_tree(self.bundle)
        self.assertTrue((self.bundle / "_internal/alias").is_symlink())
        self.assertEqual(external.read_bytes(), b"external bytes must remain")

    def test_materialization_rejects_indirect_directory_cycles(self):
        internal = self.bundle / "_internal"
        (internal / "one").mkdir()
        (internal / "two").mkdir()
        self.link(internal / "one/next", "../two", directory=True)
        self.link(internal / "two/next", "../one", directory=True)
        with self.assertRaisesRegex(ValueError, "cyclic directory link"):
            third_party.materialize_internal_tree(self.bundle)
        self.assertTrue((internal / "one/next").is_symlink())

    def test_materialization_cannot_authorize_a_stale_recorded_hash(self):
        path = self.bundle / "_internal/runtime"
        path.write_bytes(b"original")
        self.record_inventory()
        path.write_bytes(b"modified")
        self.link(self.bundle / "_internal/alias", "runtime")
        third_party.materialize_internal_tree(self.bundle)
        with self.assertRaisesRegex(ValueError, "unlisted files|missing or altered"):
            third_party.verify_inventory(self.bundle)


class ThirdPartySourceTests(unittest.TestCase):
    def test_windows_system_exclusion_preserves_exact_provenance_and_required_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "_internal").mkdir(parents=True)
            entries = []
            names = ("api-ms-win-core-console-l1-1-0.dll", "ucrtbase.dll", "VCRUNTIME140.dll",
                     "api-ms-win-core-madeup-l1-1-0.dll", "ucrtbased.dll")
            for name in names:
                source = root / "jdk" / "bin" / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"exact frozen DLL " + name.encode())
                (bundle / "_internal" / name).write_bytes(source.read_bytes())
                entries.append((name, str(source), "BINARY"))
            toc = root / "Analysis-00.toc"
            toc.write_text(repr(entries))
            def metadata(source):
                return {"CompanyName": "Microsoft Corporation", "OriginalFilename": "ucrtbase.dll" if source.name == "ucrtbase.dll" else "apisetstub",
                        "ProductName": "Microsoft® Windows® Operating System", "FileVersion": "10.0.26100.1742 (WinBuild.160101.0800)", "Machine": "0x8664"}
            with patch.object(runtime_notices, "_windows_pe_metadata", side_effect=metadata):
                excluded = third_party.exclude_windows_system_ucrt(bundle, "Windows-x64", toc)
            self.assertEqual([x["name"] for x in excluded], list(names[:2]))
            for record in excluded:
                source = Path(record["source_path"])
                self.assertTrue(source.is_file())
                self.assertEqual(record["source_sha256"], third_party.digest(source))
                self.assertEqual(record["original_bundled_sha256"], record["source_sha256"])
                self.assertIn("Windows 10", record["deployment_target"])
                self.assertFalse((bundle / record["original_bundled_path"]).exists())
            for name in names[2:]:
                self.assertTrue((bundle / "_internal" / name).is_file())

    def test_windows_system_exclusion_rejects_vendor_metadata_and_changed_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "_internal").mkdir(parents=True)
            name = "api-ms-win-core-console-l1-1-0.dll"
            source = root / name
            source.write_bytes(b"original DLL")
            payload = bundle / "_internal" / name
            payload.write_bytes(source.read_bytes())
            toc = root / "Analysis-00.toc"
            toc.write_text(repr([(name, str(source), "BINARY")]))
            with patch.object(runtime_notices, "_windows_pe_metadata", return_value={"CompanyName": "Other Vendor"}):
                self.assertEqual(third_party.exclude_windows_system_ucrt(bundle, "Windows-x64", toc), [])
            self.assertTrue(payload.is_file())
            payload.write_bytes(b"different frozen DLL")
            with self.assertRaisesRegex(ValueError, "source/payload mismatch"):
                third_party.exclude_windows_system_ucrt(bundle, "Windows-x64", toc)
            self.assertTrue(payload.is_file())

    def test_windows_system_exclusion_does_not_follow_external_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "_internal").mkdir(parents=True)
            external = root / "outside"
            external.mkdir()
            name = "ucrtbase.dll"
            source = external / name
            source.write_bytes(b"external DLL must remain")
            try:
                (bundle / "_internal" / "link").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("Symbolic links are unavailable")
            toc = root / "Analysis-00.toc"
            toc.write_text(repr([("link/" + name, str(source), "BINARY")]))
            with self.assertRaisesRegex(ValueError, "without symbolic links"):
                third_party.exclude_windows_system_ucrt(bundle, "Windows-x64", toc)
            self.assertEqual(source.read_bytes(), b"external DLL must remain")

    def test_validated_cached_source_is_used_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            path = cache / "library.tar.gz"
            data = b"exact original library source archive"
            path.write_bytes(data)
            source = {"filename": path.name, "url": "https://example.test/source", "sha256": hashlib.sha256(data).hexdigest()}
            with patch.object(third_party.urllib.request, "urlopen") as network:
                self.assertEqual(third_party.source_archive(source, cache), path)
            network.assert_not_called()

    def test_changed_cached_source_is_replaced_only_after_validated_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            path = cache / "library.tar.gz"
            path.write_bytes(b"damaged old cache")
            data = b"verified corresponding source"
            source = {"filename": path.name, "url": "https://example.test/source", "sha256": hashlib.sha256(data).hexdigest()}
            with patch.object(third_party.urllib.request, "urlopen", return_value=io.BytesIO(data)):
                third_party.source_archive(source, cache)
            self.assertEqual(path.read_bytes(), data)

    def test_bad_download_never_overwrites_original_or_leaves_partial_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            path = cache / "library.tar.gz"
            path.write_bytes(b"old source")
            source = {"filename": path.name, "url": "https://example.test/source", "sha256": "0" * 64}
            with patch.object(third_party.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong new source")):
                with self.assertRaisesRegex(ValueError, "source checksum mismatch"):
                    third_party.source_archive(source, cache)
            self.assertEqual(path.read_bytes(), b"old source")
            self.assertFalse(path.with_name(path.name + ".download").exists())

    def test_windows_dependencies_keep_actual_prebuilt_version_evidence(self):
        manifest = json.loads((third_party.CATALOG / "manifest.json").read_text())
        unix = third_party.native_component(Path("libtiff-9370c332.so.6.3.0"), manifest, "Linux-x64")
        windows = third_party.native_component(Path("libtiff-5.dll"), manifest, "Windows-x64")
        self.assertEqual(unix["version"], "4.7.2")
        self.assertIn("4.2.0", windows["version"])
        self.assertNotEqual(unix["version"], windows["version"])

    def test_windows_liblzma_follows_observed_python_pin_and_retains_exact_notice(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            destination = bundle / "third-party"
            runtime = {"python": {}, "native_libraries": [{
                "component": "CPython stdlib extension", "name": "_lzma.pyd",
            }]}
            props = b'<Project><lzmaDir Condition="$(lzmaDir) == \'\'">$(ExternalsDir)xz-5.2.5\\</lzmaDir></Project>'
            copying = b"Exact XZ constituent notice: liblzma is in the public domain.\n"
            responses = [props, copying, b"actual extension link declaration", b"actual static library declaration"]
            urls = []
            def download(url, **_kwargs):
                urls.append(url)
                return io.BytesIO(responses[len(urls) - 1])
            with patch.object(third_party.urllib.request, "urlopen", side_effect=download):
                third_party.retain_windows_liblzma_notice(bundle, destination, runtime, "3.13.9", "Windows-x64")
            record = runtime["python"]["windows_liblzma"]
            self.assertEqual(record["cpython_reference"], "v3.13.9")
            self.assertEqual(record["source_reference"], "xz-5.2.5")
            self.assertIn("/v3.13.9/PCbuild/python.props", urls[0])
            self.assertIn("/xz-5.2.5/COPYING", urls[1])
            self.assertEqual(record["bundled_objects"], ["_lzma.pyd"])
            self.assertEqual((bundle / record["notice"]["path"]).read_bytes(), copying)
            self.assertEqual(record["notice"]["sha256"], hashlib.sha256(copying).hexdigest())
            self.assertEqual(len(record["build_provenance"]), 3)

    def test_windows_liblzma_is_not_inferred_from_other_modules_or_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            for platform, objects in (
                ("Windows-x64", [{"component": "CPython stdlib extension", "name": "_socket.pyd"}]),
                ("Windows-x64", []),
                ("Linux-x64", [{"component": "CPython stdlib extension", "name": "_lzma.pyd"}]),
            ):
                runtime = {"python": {}, "native_libraries": objects}
                with self.subTest(platform=platform, objects=objects), patch.object(third_party.urllib.request, "urlopen") as network:
                    third_party.retain_windows_liblzma_notice(bundle, bundle / "third-party", runtime, "3.13.9", platform)
                    network.assert_not_called()
                self.assertNotIn("windows_liblzma", runtime["python"])

    def test_windows_liblzma_ambiguous_source_pin_stops_notice_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            runtime = {"python": {}, "native_libraries": [{
                "component": "CPython stdlib extension", "name": "_lzma.pyd",
            }]}
            with patch.object(third_party.urllib.request, "urlopen", return_value=io.BytesIO(b"no verified source pin")):
                with self.assertRaisesRegex(ValueError, "no unambiguous liblzma source pin"):
                    third_party.retain_windows_liblzma_notice(bundle, bundle / "third-party", runtime, "3.13.9", "Windows-x64")
            self.assertNotIn("windows_liblzma", runtime["python"])

    def test_source_archive_inventory_requires_the_actual_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            source = bundle / "third-party/sources/library.tar.gz"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"library source")
            inventory = {"schema_version": 1, "payload": [], "source_archives": [{
                "path": source.relative_to(bundle).as_posix(), "sha256": third_party.digest(source),
            }]}
            (bundle / third_party.INVENTORY_NAME).write_text(json.dumps(inventory))
            third_party.verify_inventory(bundle)
            source.unlink()
            with self.assertRaisesRegex(ValueError, "missing or altered runtime/source"):
                third_party.verify_inventory(bundle)

    def test_inventory_rejects_external_links_and_portable_escape_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            bundle.mkdir()
            external = root / "outside.txt"
            external.write_bytes(b"matching external bytes")
            for path in ("../outside.txt", "C:/outside.txt", "..\\outside.txt", "/outside.txt"):
                inventory = {"schema_version": 1, "payload": [{"path": path, "sha256": third_party.digest(external)}]}
                (bundle / third_party.INVENTORY_NAME).write_text(json.dumps(inventory))
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "leaves the player folder"):
                    third_party.verify_inventory(bundle)
            if hasattr(Path, "symlink_to"):
                try:
                    (bundle / "_internal").mkdir()
                    (bundle / "_internal/linked.txt").symlink_to(external)
                except OSError:
                    return
                inventory = {"schema_version": 1, "payload": [{"path": "_internal/linked.txt", "sha256": third_party.digest(external)}]}
                (bundle / third_party.INVENTORY_NAME).write_text(json.dumps(inventory))
                with self.assertRaisesRegex(ValueError, "without symbolic links"):
                    third_party.verify_inventory(bundle)

    def test_font_free_library_source_preserves_every_implementation_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "upstream.tar.gz"
            contents = {
                "setup.py": b'data_files = ["src_py/freesansbold.ttf", "icon.bmp"]\n',
                "src_py/meson.build": b"data_files = files(\n    'freesansbold.ttf',\n    'icon.bmp',\n)\n",
                "src_c/font.c": b"int library_function(void) { return 7; }\n",
                "docs/LGPL.txt": b"Original library license\n",
                "src_py/freesansbold.ttf": b"Unused independent default font",
                "examples/data/sans.ttf": b"Unused example font",
            }
            with tarfile.open(source, "w:gz") as archive:
                for name, data in contents.items():
                    info = tarfile.TarInfo("pygame_ce-2.5.8/" + name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            first, second = work / "first.tar.gz", work / "second.tar.gz"
            report = third_party.pygame_library_source(source, first)
            third_party.pygame_library_source(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(set(report["omitted_resources"]), {"src_py/freesansbold.ttf", "examples/data/sans.ttf"})
            with tarfile.open(first) as archive:
                names = archive.getnames()
                self.assertFalse(any(name.endswith(".ttf") for name in names))
                for name in ("src_c/font.c", "docs/LGPL.txt"):
                    self.assertEqual(archive.extractfile("pygame_ce-2.5.8/" + name).read(), contents[name])
                for name in ("setup.py", "src_py/meson.build"):
                    data = archive.extractfile("pygame_ce-2.5.8/" + name).read()
                    self.assertIn(b"2026-10-02", data)
                    self.assertNotIn(b'"src_py/freesansbold.ttf",', data)
                self.assertIn("pygame_ce-2.5.8/RBS-SOURCE-CHANGES.txt", names)


if __name__ == "__main__":
    unittest.main()
