"""Runtime notices follow the frozen payload and installed provenance."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import runtime_notices


class RuntimeNoticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stdlib = self.root / "python" / "lib" / "python3.13"
        self.stdlib.mkdir(parents=True)
        self.license = self.stdlib / "LICENSE.txt"
        self.license.write_text("Python Software Foundation LICENSE and copyright\n")
        self.installer_root = self.root / "installer"
        self.installer_license = self.installer_root / "pyinstaller-6.22.0.dist-info" / "licenses" / "COPYING.txt"
        self.installer_license.parent.mkdir(parents=True)
        self.installer_license.write_text("PyInstaller copyright, GPL bootloader exception, Apache and MIT\n")
        self.distribution = SimpleNamespace(
            version="6.22.0", files=[self.installer_license.relative_to(self.installer_root)],
            locate_file=lambda entry: self.installer_root / entry,
        )
        self.bundle = self.root / "game"
        self.internal = self.bundle / "_internal"
        self.internal.mkdir(parents=True)
        self.destination = self.bundle / "licenses"
        self.toc = self.root / "Analysis-00.toc"
        self.entries = []
        patches = (
            patch.object(runtime_notices.sysconfig, "get_path", return_value=str(self.stdlib)),
            patch.object(runtime_notices.sys, "base_prefix", str(self.root / "python")),
            patch.object(runtime_notices.metadata, "distribution", return_value=self.distribution),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def native(self, name, source, *, kind="BINARY", shipped=True):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"original native library\n")
        self.entries.append((name, str(source), kind))
        if shipped:
            target = self.internal / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"frozen native library\n")
        return source

    def collect(self):
        # Analysis fields and list ordering differ between PyInstaller releases.
        # Include a repeated tuple to exercise inventory deduplication.
        self.toc.write_text(repr(([], {"nested": [self.entries, self.entries[:1]]}, False)))
        return runtime_notices.collect_runtime_notices(self.bundle, self.toc, self.destination)

    def test_frozen_stdlib_and_hook_notices_preserve_source_bytes_and_inventory(self):
        logging = self.stdlib / "logging" / "__init__.py"
        logging.parent.mkdir()
        original = b"# Copyright fixture author\n# Permission and warranty notice\nvalue = 1\n"
        logging.write_bytes(original)
        third_party = self.stdlib / "site-packages" / "unrelated.py"
        third_party.parent.mkdir()
        third_party.write_text("must not be treated as CPython\n")
        hook = self.installer_root / "PyInstaller" / "hooks" / "rthooks" / "pyi_rth_inspect.py"
        hook.parent.mkdir(parents=True)
        hook.write_text("# Copyright runtime-hook author\n# Apache-2.0\npass\n")
        self.entries.extend([
            ("logging", str(logging), "PYMODULE"),
            ("unrelated", str(third_party), "PYMODULE"),
            ("pyi_rth_inspect", str(hook), "PYSOURCE"),
        ])
        report = self.collect()
        self.assertEqual([record["module"] for record in report["stdlib_sources"]], ["logging"])
        record = report["stdlib_sources"][0]
        self.assertEqual((self.destination / record["notice_path"]).read_bytes(), original)
        self.assertEqual(record["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(report["runtime_hooks"][0]["module"], "pyi_rth_inspect")
        self.assertEqual((self.destination / "PyInstaller/COPYING.txt").read_bytes(), self.installer_license.read_bytes())
        self.assertEqual(json.loads((self.destination / "inventory.json").read_text()), report)
        self.assertEqual(report["unresolved"], [])

    def test_unbundled_system_and_separately_collected_pygame_libraries_do_not_resolve_dpkg(self):
        self.native("libunused.so", self.root / "system" / "libunused.so", shipped=False)
        self.native("pygame_ce.libs/libSDL2.so", self.root / "site-packages" / "pygame_ce.libs" / "libSDL2.so")
        with patch.object(runtime_notices, "_dpkg_package") as lookup:
            report = self.collect()
        lookup.assert_not_called()
        self.assertEqual(report["native_libraries"], [])
        self.assertEqual(len(report["excluded_native_entries"]), 2)
        self.assertEqual(report["unresolved"], [])

    def test_actual_debian_binary_copies_package_and_referenced_full_license(self):
        source = self.native("libexample.so.1", self.root / "system" / "libexample.so.1")
        docs = self.root / "doc"
        copyright = docs / "libexample1" / "copyright"
        copyright.parent.mkdir(parents=True)
        copyright.write_text("Copyright example\nFull license: /usr/share/common-licenses/LGPL-2.1\n")
        common = self.root / "common-licenses"
        common.mkdir()
        (common / "LGPL-2.1").write_text("Exact complete LGPL fixture text\n")
        calls = []
        def command(arguments):
            calls.append(arguments)
            output = "libexample1:amd64: " + str(source) + "\n" if "--search" in arguments else "libexample1:amd64\t1.2-3\texample\t1.2-3\n"
            return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")
        with patch.object(runtime_notices.sys, "platform", "linux"), patch.object(
            runtime_notices.shutil, "which", return_value="/usr/bin/dpkg-query"
        ), patch.object(runtime_notices, "_command", side_effect=command), patch.object(
            runtime_notices, "DOC_ROOT", docs
        ), patch.object(runtime_notices, "COMMON_LICENSES_ROOT", common):
            report = self.collect()
        library = report["native_libraries"][0]
        self.assertEqual(library["package_provenance"], {"package": "libexample1:amd64", "version": "1.2-3", "source_package": "example", "source_version": "1.2-3"})
        self.assertNotEqual(library["source_sha256"], library["bundled_sha256"])
        notices = {Path(record["notice_path"]).name: record for record in library["notices"]}
        self.assertEqual(set(notices), {"copyright.txt", "LGPL-2.1"})
        self.assertEqual((self.destination / notices["LGPL-2.1"]["notice_path"]).read_bytes(), (common / "LGPL-2.1").read_bytes())
        self.assertEqual(report["unresolved"], [])
        self.assertEqual(len(calls), 2)

    def test_missing_referenced_common_license_is_reported(self):
        self.native("libexample.so", self.root / "system" / "libexample.so")
        docs = self.root / "doc"
        copyright = docs / "libexample" / "copyright"
        copyright.parent.mkdir(parents=True)
        copyright.write_text("See /usr/share/common-licenses/GPL-3\n")
        with patch.object(runtime_notices.sys, "platform", "linux"), patch.object(
            runtime_notices, "_dpkg_package", return_value={"package": "libexample", "version": "1", "source_package": "example", "source_version": "1"}
        ), patch.object(runtime_notices, "DOC_ROOT", docs), patch.object(runtime_notices, "COMMON_LICENSES_ROOT", self.root / "missing"):
            report = self.collect()
        self.assertEqual(len(report["native_libraries"][0]["notices"]), 1)
        self.assertIn("Referenced common license is unavailable", report["unresolved"][0]["reason"])

    def test_windows_crt_requires_microsoft_notice_instead_of_psf_license(self):
        source = self.native("vcruntime140.dll", self.root / "python" / "vcruntime140.dll")
        (source.parent / "LICENSE.txt").write_text("Python Software Foundation LICENSE\n")
        identity = {"CompanyName": "Microsoft Corporation", "OriginalFilename": source.name, "FileVersion": "14.51.36247.0"}
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True), patch.object(runtime_notices, "_windows_pe_metadata", return_value=identity):
            report = self.collect()
        self.assertEqual(report["native_libraries"][0]["notices"], [])
        self.assertEqual(report["unresolved"][0]["component"], "vcruntime140.dll")
        (source.parent / "license.rtf").write_text("Microsoft Software License Terms\nMicrosoft Visual C++ 2015–2026 Runtime\nYou may install and use the software under these terms.\n")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True), patch.object(runtime_notices, "_windows_pe_metadata", return_value=identity):
            report = self.collect()
        self.assertEqual(len(report["native_libraries"][0]["notices"]), 1)
        self.assertEqual(report["unresolved"], [])

    def test_windows_crt_finds_actual_vs_license_through_vswhere_without_vc_environment(self):
        self.native("vcruntime140.dll", self.root / "python" / "vcruntime140.dll")
        program_files = self.root / "Program Files (x86)"
        vswhere = program_files / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        vswhere.parent.mkdir(parents=True)
        vswhere.write_bytes(b"installed locator fixture")
        studio = self.root / "Visual Studio" / "2022" / "Enterprise"
        notice = studio / "Licenses" / "1033" / "VS_EULA.rtf"
        notice.parent.mkdir(parents=True)
        notice.write_text("Microsoft Software License Terms\nMicrosoft Visual C++ 2015–2026 Runtime\nYou may install and use the software under these terms.\n")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(
            runtime_notices.os.environ, {"ProgramFiles(x86)": str(program_files)}, clear=True
        ), patch.object(runtime_notices, "_command", return_value=subprocess.CompletedProcess([], 0, stdout=str(studio) + "\n")) as command, patch.object(
            runtime_notices, "_windows_pe_metadata", return_value={"CompanyName": "Microsoft Corporation", "OriginalFilename": "vcruntime140.dll", "FileVersion": "14.51.36247.0"}
        ):
            report = self.collect()
        self.assertEqual(command.call_args.args[0][0], str(vswhere))
        self.assertEqual(report["native_libraries"][0]["notices"][0]["source_path"], str(notice))
        self.assertEqual(report["unresolved"], [])

    def test_python_windows_runtime_conditions_require_installed_origin_and_microsoft_identity(self):
        source = self.native("VCRUNTIME140.dll", self.root / "python" / "VCRUNTIME140.dll")
        conditions = (
            "Additional Conditions for this Windows binary build\n"
            "This program is linked with and uses Microsoft Distributable Code, copyrighted by Microsoft Corporation.\n"
            "Redistribution of the Windows binary build of the Python interpreter complies with this agreement, provided that you do not alter copyright notices.\n"
        )
        self.license.write_text("Python Software Foundation LICENSE\n\n" + conditions)
        identity = {"CompanyName": "Microsoft Corporation", "OriginalFilename": source.name, "FileVersion": "14.51.36247.0"}
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True), patch.object(runtime_notices, "_windows_pe_metadata", return_value=identity):
            report = self.collect()
        library = report["native_libraries"][0]
        self.assertEqual(library["notices"], report["python"]["notices"])
        self.assertIn("verified interpreter-root DLL provenance", library["notice_resolution"])
        self.assertEqual(report["unresolved"], [])
        self.assertEqual((self.destination / library["notices"][0]["notice_path"]).read_bytes(), self.license.read_bytes())

        self.entries.clear()
        external = self.native("VCRUNTIME140.dll", self.root / "unrelated package" / "VCRUNTIME140.dll")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True), patch.object(runtime_notices, "_windows_pe_metadata", return_value=identity):
            report = self.collect()
        self.assertEqual(report["native_libraries"][0]["notices"], [])
        self.assertEqual(report["unresolved"][0]["source_path"], str(external))

    def test_unrelated_microsoft_documents_and_named_vendor_dll_cannot_resolve_runtime(self):
        for text in (
            "Microsoft Entity Framework Designer for Visual Studio 2012. Distributable Code terms.",
            "Distributable Code for Microsoft Visual Studio\nVisit https://aka.ms/vs/18/redistribution.",
            "ThirdPartyNotices: Microsoft Visual Studio incorporates runtime redistributable libraries.",
        ):
            self.assertFalse(runtime_notices._microsoft_runtime_notice(text), text)
        source = self.native("vcruntime-fake.dll", self.root / "vendor" / "vcruntime-fake.dll")
        (source.parent / "LICENSE.txt").write_text("Microsoft Software License Terms\nMicrosoft Visual C++ 2026 Runtime\nYou may install and use the software.\n")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True):
            report = self.collect()
        self.assertEqual(report["native_libraries"][0]["notices"], [])
        self.assertEqual(report["unresolved"][0]["component"], "vcruntime-fake.dll")

    def test_explicit_python_component_notice_resolves_openssl_but_keeps_other_libraries_unresolved(self):
        self.native("libcrypto-3.dll", self.root / "python" / "DLLs" / "libcrypto-3.dll")
        self.native("unrelated.dll", self.root / "python" / "DLLs" / "unrelated.dll")
        notice = self.root / "cpython-version-matched-Doc-license.rst"
        notice.write_text("OpenSSL\n=======\nExact upstream component license fixture\n")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(
            runtime_notices.os.environ, {"RBS_CPYTHON_NOTICE_SOURCE": str(notice)}, clear=True
        ):
            report = self.collect()
        libraries = {item["name"]: item for item in report["native_libraries"]}
        self.assertEqual(libraries["libcrypto-3.dll"]["notices"], report["python"]["additional_notices"])
        self.assertEqual(libraries["unrelated.dll"]["notices"], [])
        self.assertEqual([item["component"] for item in report["unresolved"]], ["unrelated.dll"])

    def test_component_aliases_require_their_exact_named_upstream_notice_sections(self):
        notice = self.root / "license.rst"
        notice.write_text("zlib\n====\nComplete zlib notice fixture\n\nexpat\n=====\nComplete expat notice fixture\nThis text mentions bzip2 but supplies no section.\n")
        for name in ("libz.so.1", "zlib1.dll", "libexpat-1.dll", "libexpat.1.dylib"):
            self.assertTrue(runtime_notices._python_component_in_notice(name, notice), name)
        for name in ("libbz2.so.1", "liblzma.so.5", "libcrypto-3.dll", "unrelated.dll"):
            self.assertFalse(runtime_notices._python_component_in_notice(name, notice), name)
        notice.write_text("bzip2\n=====\nComplete bzip2 notice fixture\n")
        self.assertTrue(runtime_notices._python_component_in_notice("libbz2.so.1", notice))
        self.assertFalse(runtime_notices._python_component_in_notice("libz.so.1", notice))

    def test_ssl_versions_and_exact_upstream_refs_are_recorded_for_bundled_crypto(self):
        self.native("libcrypto-3.dll", self.root / "python" / "DLLs" / "libcrypto-3.dll")
        ssl = SimpleNamespace(OPENSSL_VERSION="OpenSSL 3.5.7 9 Aug 2026", OPENSSL_VERSION_INFO=(3, 5, 7, 0, 0))
        native_ssl = SimpleNamespace(_OPENSSL_API_VERSION=(3, 0, 0, 0, 0))
        with patch.dict("sys.modules", {"ssl": ssl, "_ssl": native_ssl}), patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True):
            report = self.collect()
        info = report["native_libraries"][0]["openssl_provenance"]
        self.assertEqual(info["runtime_version_info"], [3, 5, 7, 0, 0])
        self.assertEqual(info["compiled_api_version"], [3, 0, 0, 0, 0])
        self.assertEqual(info["upstream_sources"]["reference"], "openssl-3.5.7")
        self.assertEqual(info["upstream_sources"]["license_url"], "https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.7/LICENSE.txt")
        self.assertEqual(info["upstream_sources"]["notice_url"], "https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.7/NOTICE")

    def test_actual_cpython_library_uses_installed_cpython_notice(self):
        self.native("libpython3.13.so.1.0", self.root / "python" / "lib" / "libpython3.13.so.1.0")
        with patch.object(runtime_notices, "_dpkg_package") as lookup:
            report = self.collect()
        lookup.assert_not_called()
        library = report["native_libraries"][0]
        self.assertEqual(library["component"], "CPython runtime")
        self.assertEqual(library["notices"], report["python"]["notices"])

    def test_windows_dlls_stdlib_extensions_keep_cpython_notices_without_covering_vendor(self):
        self.native("_socket.pyd", self.root / "python" / "DLLs" / "_socket.pyd", kind="EXTENSION")
        self.native("vendor.pyd", self.root / "python" / "DLLs" / "vendor.pyd", kind="EXTENSION")
        with patch.object(runtime_notices.sys, "platform", "win32"), patch.dict(runtime_notices.os.environ, {}, clear=True):
            report = self.collect()
        libraries = {item["name"]: item for item in report["native_libraries"]}
        self.assertEqual(libraries["_socket.pyd"]["component"], "CPython stdlib extension")
        self.assertEqual(libraries["_socket.pyd"]["notices"], report["python"]["notices"])
        self.assertEqual(libraries["vendor.pyd"]["notices"], [])
        self.assertEqual([item["component"] for item in report["unresolved"]], ["vendor.pyd"])

    def test_macos_collected_cellar_library_preserves_its_installed_package_notice(self):
        source = self.native("libexample.dylib", self.root / "Cellar" / "example" / "1.2" / "lib" / "libexample.dylib")
        license = source.parent.parent / "COPYING"
        license.write_text("Installed example library copyright and license\n")
        with patch.object(runtime_notices.sys, "platform", "darwin"), patch.object(runtime_notices, "_dpkg_package") as lookup:
            report = self.collect()
        lookup.assert_not_called()
        notice = report["native_libraries"][0]["notices"][0]
        self.assertEqual((self.destination / notice["notice_path"]).read_bytes(), license.read_bytes())
        self.assertEqual(notice["source_path"], str(license))
        self.assertEqual(report["unresolved"], [])

    def test_unavailable_native_notice_keeps_exact_file_provenance_and_unresolved_status(self):
        source = self.native("libunowned.so", self.root / "unowned" / "libunowned.so")
        with patch.object(runtime_notices, "_dpkg_package", return_value=None):
            report = self.collect()
        library = report["native_libraries"][0]
        self.assertEqual(library["source_path"], str(source))
        self.assertEqual(library["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(library["notices"], [])
        self.assertEqual(report["unresolved"][0]["component"], "libunowned.so")

    def test_missing_primary_licenses_fail_before_creating_notices(self):
        self.license.unlink()
        with self.assertRaisesRegex(ValueError, "CPython LICENSE"):
            self.collect()
        self.assertFalse(self.destination.exists())
        self.license.write_text("Python LICENSE")
        self.installer_license.unlink()
        with self.assertRaisesRegex(ValueError, "PyInstaller COPYING"):
            self.collect()
        self.assertFalse(self.destination.exists())

    def test_toc_parsing_does_not_execute_python(self):
        marker = self.root / "executed"
        self.toc.write_text(f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')")
        with self.assertRaisesRegex(ValueError, "valid literal inventory"):
            runtime_notices.collect_runtime_notices(self.bundle, self.toc, self.destination)
        self.assertFalse(marker.exists())
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
