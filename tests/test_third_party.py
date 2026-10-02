"""Player packages retain verified library sources and auditable notices."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from scripts import third_party


class ThirdPartySourceTests(unittest.TestCase):
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
                    (bundle / "linked.txt").symlink_to(external)
                except OSError:
                    return
                inventory = {"schema_version": 1, "payload": [{"path": "linked.txt", "sha256": third_party.digest(external)}]}
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
