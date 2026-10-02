"""Preserve notices and provenance for an actual PyInstaller desktop payload.

Run with the interpreter used to freeze the app. This collector does not fetch
sources or decide whether a library's redistribution terms have been met.
Unresolved native notices remain explicit so the release builder can supply
the corresponding upstream notice/source artifacts before publication.
"""

from __future__ import annotations

import ast
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import Iterator


DOC_ROOT = Path("/usr/share/doc")
COMMON_LICENSES_ROOT = Path("/usr/share/common-licenses")
TOC_KINDS = {"BINARY", "EXTENSION", "PYMODULE", "PYSOURCE", "DATA", "SYMLINK"}


def _entries(value: object) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, (tuple, list)):
        if len(value) == 3 and all(isinstance(item, str) for item in value) and value[2] in TOC_KINDS:
            yield tuple(value)
        else:
            for item in value:
                yield from _entries(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _entries(item)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_notice(source: Path, destination: Path, relative: Path) -> dict:
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {"source_path": str(source), "notice_path": relative.as_posix(), "sha256": _digest(target)}


def _stdlib_relative(source: Path, stdlib: Path) -> Path | None:
    try:
        relative = source.resolve().relative_to(stdlib)
    except ValueError:
        return None
    if "site-packages" in relative.parts or "dist-packages" in relative.parts:
        return None
    return relative


def _stdlib_extension(source: Path, relative: Path | None) -> bool:
    if relative is not None:
        return True
    # The Windows installer keeps standard C extensions in DLLs rather than
    # Lib. Require both that installed location and a known stdlib module;
    # an unrelated vendor extension is not covered by CPython's license.
    try:
        source.resolve().relative_to((Path(sys.base_prefix) / "DLLs").resolve())
    except ValueError:
        return False
    return source.name.split(".", 1)[0] in getattr(sys, "stdlib_module_names", ())


def _python_licenses(stdlib: Path) -> list[Path]:
    candidates = (
        stdlib / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt",
        stdlib.parent / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
    )
    found = []
    seen = set()
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() not in seen:
            found.append(candidate)
            seen.add(candidate.resolve())
    if not found:
        raise ValueError("The installed CPython LICENSE could not be located")
    return found


def _pyinstaller_license() -> tuple[str, Path]:
    try:
        distribution = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError as error:
        raise ValueError("PyInstaller must be installed to collect its runtime license") from error
    for entry in distribution.files or ():
        if Path(entry).name == "COPYING.txt":
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                return distribution.version, source
    raise ValueError("The installed PyInstaller COPYING.txt could not be located")


def _bundled_path(bundle: Path, name: str) -> Path | None:
    relative = PurePosixPath(name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
        return None
    for prefix in (bundle / "_internal", bundle):
        path = prefix.joinpath(*relative.parts)
        if path.is_file():
            return path
    return None


def _pygame_native(name: str, source: Path) -> bool:
    parts = {part.lower() for part in source.parts} | set(name.lower().replace("\\", "/").split("/"))
    return bool(parts & {"pygame", "pygame.libs", "pygame_ce.libs"})


def _command(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)


def _dpkg_package(source: Path) -> dict | None:
    if not shutil.which("dpkg-query"):
        return None
    candidates = [source, source.resolve()]
    for candidate in tuple(candidates):
        text = str(candidate)
        if text.startswith(("/lib/", "/lib64/", "/bin/", "/sbin/")):
            candidates.append(Path("/usr" + text))
        elif text.startswith(("/usr/lib/", "/usr/lib64/", "/usr/bin/", "/usr/sbin/")):
            candidates.append(Path(text[4:]))
    for candidate in dict.fromkeys(candidates):
        result = _command(["dpkg-query", "--search", str(candidate)])
        if result.returncode:
            continue
        for line in result.stdout.splitlines():
            package, separator, _path = line.rpartition(": ")
            if not separator or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?", package):
                continue
            details = _command([
                "dpkg-query", "--show", "--showformat=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n", package,
            ])
            fields = details.stdout.strip().split("\t")
            if details.returncode or len(fields) != 4:
                continue
            return {"package": fields[0], "version": fields[1], "source_package": fields[2], "source_version": fields[3]}
    return None


def _debian_notices(package: dict, destination: Path) -> tuple[list[dict], list[str]]:
    name = package["package"].split(":", 1)[0]
    source = DOC_ROOT / name / "copyright"
    if not source.is_file():
        return [], [f"Installed package {package['package']} has no copyright file at {source}"]
    relative = Path("Native") / "Debian" / name
    notices = [_copy_notice(source, destination, relative / "copyright.txt")]
    missing = []
    text = source.read_text(encoding="utf-8", errors="replace")
    # Copy only full license files actually referenced by this package notice.
    references = sorted({name.rstrip(".") for name in re.findall(r"/usr/share/common-licenses/([A-Za-z0-9_.+-]+)", text)})
    for reference in references:
        license_path = COMMON_LICENSES_ROOT / reference
        if license_path.is_file():
            notices.append(_copy_notice(license_path, destination, relative / license_path.name))
        else:
            missing.append(f"Referenced common license is unavailable: {license_path}")
    return notices, missing


def _installed_native_notices(source: Path) -> list[Path]:
    """Use an actual package prefix, or a component-specific adjacent notice."""
    roots = [source.parent, source.parent.parent]
    if "Cellar" in source.parts:
        index = source.parts.index("Cellar")
        if len(source.parts) > index + 2:
            roots.append(Path(*source.parts[:index + 3]))
    crt = source.name.lower().startswith(("vcruntime", "msvcp", "concrt", "ucrtbase"))
    if crt:
        for variable in ("VCToolsRedistDir", "VCINSTALLDIR"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]))
    found = []
    for root in dict.fromkeys(roots):
        if not root.is_dir():
            continue
        for pattern in ("LICENSE*", "COPYING*", "copyright*", "license*", "EULA*", "eula*"):
            for candidate in root.glob(pattern):
                if not candidate.is_file():
                    continue
                text = candidate.read_text(encoding="utf-8", errors="replace")
                if crt:
                    applicable = _microsoft_runtime_notice(text)
                elif "Cellar" in source.parts:
                    applicable = True
                else:
                    # The interpreter's PSF license is not an OpenSSL/CRT notice.
                    tokens = [token for token in ("openssl", "sqlite", "libffi", "bzip", "xz", "liblzma") if token in source.name.lower()]
                    if source.name.lower().startswith(("libssl", "libcrypto")):
                        tokens.append("openssl")
                    applicable = bool(tokens) and any(token in text.lower() for token in tokens)
                if applicable and candidate.resolve() not in {path.resolve() for path in found}:
                    found.append(candidate)
    if crt and sys.platform == "win32":
        found.extend(path for path in _visual_studio_notices() if path.resolve() not in {item.resolve() for item in found})
    return found


def _microsoft_runtime_notice(text: str) -> bool:
    lowered = text.lower()
    return "microsoft" in lowered and any(token in lowered for token in ("visual c++", "visual studio", "visual c")) and any(
        token in lowered for token in ("redistribut", "distributable code")
    )


def _visual_studio_notices() -> list[Path]:
    """Discover actual installed VS licenses, without assuming an edition."""
    roots = []
    if os.environ.get("VSINSTALLDIR"):
        roots.append(Path(os.environ["VSINSTALLDIR"]))
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if not os.environ.get(variable):
            continue
        vswhere = Path(os.environ[variable]) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere.is_file():
            continue
        result = _command([str(vswhere), "-latest", "-products", "*", "-property", "installationPath", "-utf8"])
        if not result.returncode:
            roots.extend(Path(line.strip()) for line in result.stdout.splitlines() if line.strip())
    found = []
    for root in dict.fromkeys(roots):
        for pattern in (
            "Licenses/*/*.rtf", "Licenses/*/*.txt", "Licenses/*.rtf",
            "VC/Redist/MSVC/*/LICENSE*", "VC/Redist/MSVC/*/license*",
        ):
            for candidate in root.glob(pattern):
                if candidate.is_file() and _microsoft_runtime_notice(candidate.read_text(encoding="utf-8", errors="replace")):
                    if candidate.resolve() not in {path.resolve() for path in found}:
                        found.append(candidate)
    return found


def _explicit_python_notice() -> Path | None:
    source = os.environ.get("RBS_CPYTHON_NOTICE_SOURCE")
    if not source:
        return None
    path = Path(source)
    if not path.is_file():
        raise ValueError("RBS_CPYTHON_NOTICE_SOURCE does not identify an existing notice artifact")
    return path


def _python_component_in_notice(name: str, notice: Path) -> bool:
    lowered = name.lower()
    aliases = (
        (r"^(libssl|libcrypto|ssleay|libeay)", {"openssl"}),
        (r"^(libz([.-]|$)|zlib)", {"zlib"}),
        (r"^libexpat", {"expat"}),
        (r"^libffi", {"libffi"}),
        (r"^(libmpdec|mpdecimal)", {"libmpdec"}),
        (r"^(libbz2|libbzip2|bzip2)", {"bzip2", "bzip"}),
        (r"^(liblzma|lzma)", {"liblzma", "lzma"}),
        (r"^(libsqlite|sqlite)", {"sqlite", "sqlite3"}),
    )
    components = set().union(*(sections for pattern, sections in aliases if re.search(pattern, lowered)))
    lines = notice.read_text(encoding="utf-8", errors="replace").splitlines()
    headings = {
        title.strip().lower()
        for title, underline in zip(lines, lines[1:])
        if title.strip() and len(underline.strip()) >= 3 and len(set(underline.strip())) == 1 and underline.strip()[0] in "=-~^"
    }
    return bool(components & headings)


def _openssl_inventory() -> dict:
    """Describe the build interpreter's linked SSL, without fetching sources."""
    try:
        import ssl
        import _ssl
    except ImportError as error:
        return {"available": False, "reason": str(error)}
    info = {
        "available": True, "version_observed_from": "Build interpreter ssl module",
        "runtime_version": ssl.OPENSSL_VERSION,
        "runtime_version_info": list(ssl.OPENSSL_VERSION_INFO),
        "compiled_api_version": list(getattr(_ssl, "_OPENSSL_API_VERSION", ())),
    }
    match = re.match(r"OpenSSL\s+(\d+\.\d+\.\d+[a-z]?)\b", ssl.OPENSSL_VERSION)
    if match:
        version = match[1]
        modern = int(version.split(".")[0]) >= 3
        reference = f"openssl-{version}" if modern else "OpenSSL_" + version.replace(".", "_")
        base = f"https://raw.githubusercontent.com/openssl/openssl/{reference}"
        info["upstream_sources"] = {
            "version": version, "reference": reference,
            "license_url": base + ("/LICENSE.txt" if modern else "/LICENSE"),
            "source_archive_url": f"https://github.com/openssl/openssl/archive/refs/tags/{reference}.tar.gz",
        }
        if modern:
            info["upstream_sources"]["notice_url"] = base + "/NOTICE"
    return info


def collect_runtime_notices(bundle_dir: Path, analysis_toc: Path, destination: Path) -> dict:
    """Copy observed runtime notices; return and save a JSON-safe inventory.

    Only CPython and PyInstaller's primary missing licenses are fatal here.
    The caller must review ``unresolved`` before publishing native downloads.
    Pygame and its native dependencies are inventoried separately by the
    release builder, and are explicitly listed as excluded from this helper.
    ``RBS_CPYTHON_NOTICE_SOURCE`` can identify an additional upstream notice
    artifact supplied by the builder (for example, version-matched CPython
    ``Doc/license.rst``). The builder verifies its version and provenance; this
    helper copies it byte-for-byte and records its hash without fetching it.
    """
    bundle_dir, analysis_toc, destination = map(Path, (bundle_dir, analysis_toc, destination))
    try:
        toc = ast.literal_eval(analysis_toc.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValueError("PyInstaller Analysis TOC is not a valid literal inventory") from error
    entries = sorted(set(_entries(toc)))
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    python_licenses = _python_licenses(stdlib)
    installer_version, installer_license = _pyinstaller_license()
    additional_python_notice = _explicit_python_notice()
    destination.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1, "platform": sys.platform, "analysis_toc": str(analysis_toc),
        "scope": "Observed frozen files and supplied notice artifacts. Statically incorporated third-party dependencies require a separate upstream source/license inventory.",
        "analysis_sha256": _digest(analysis_toc),
        "python": {"version": sys.version, "stdlib": str(stdlib), "base_prefix": sys.base_prefix,
                   "config_args": sysconfig.get_config_var("CONFIG_ARGS"), "native_link_flags": sysconfig.get_config_var("MODLIBS"), "openssl": _openssl_inventory(), "notices": [], "additional_notices": []},
        "pyinstaller": {"version": installer_version, "notice": _copy_notice(installer_license, destination, Path("PyInstaller/COPYING.txt"))},
        "stdlib_sources": [], "runtime_hooks": [], "native_libraries": [], "excluded_native_entries": [], "unresolved": [],
    }
    for number, source in enumerate(python_licenses, 1):
        report["python"]["notices"].append(_copy_notice(source, destination, Path("CPython") / f"LICENSE-{number}.txt"))
    if additional_python_notice:
        report["python"]["additional_notices"].append(_copy_notice(additional_python_notice, destination, Path("CPython/upstream-notices") / additional_python_notice.name))
    copied_sources = set()
    for name, source_text, kind in entries:
        source = Path(source_text)
        relative = _stdlib_relative(source, stdlib)
        if kind == "PYMODULE" and relative is not None and source.suffix == ".py":
            if source.is_file() and source.resolve() not in copied_sources:
                record = _copy_notice(source, destination, Path("CPython/stdlib-source") / relative)
                report["stdlib_sources"].append({"module": name, **record})
                copied_sources.add(source.resolve())
            elif not source.is_file():
                report["unresolved"].append({"component": name, "source_path": source_text, "reason": "Frozen stdlib source is no longer installed"})
        if kind == "PYSOURCE" and (name.startswith("pyi_rth_") or "rthooks" in source.parts):
            if source.is_file():
                report["runtime_hooks"].append({"module": name, **_copy_notice(source, destination, Path("PyInstaller/runtime-sources") / source.name)})
            else:
                report["unresolved"].append({"component": name, "source_path": source_text, "reason": "Embedded runtime hook source is unavailable"})
        if kind not in {"BINARY", "EXTENSION"}:
            continue
        bundled = _bundled_path(bundle_dir, name)
        if bundled is None:
            report["excluded_native_entries"].append({"name": name, "source_path": source_text, "reason": "Not present in the desktop payload"})
            continue
        if _pygame_native(name, source):
            report["excluded_native_entries"].append({"name": name, "source_path": source_text, "reason": "Pygame native inventory is collected separately"})
            continue
        native = {"name": name, "source_path": source_text, "bundled_path": str(bundled), "bundled_sha256": _digest(bundled), "notices": []}
        if source.name.lower().startswith(("libssl", "libcrypto", "ssleay", "libeay")):
            native["openssl_provenance"] = report["python"]["openssl"]
        report["native_libraries"].append(native)
        if not source.is_file():
            report["unresolved"].append({"component": name, "source_path": source_text, "reason": "Native build source file is unavailable"})
            continue
        native["source_sha256"] = _digest(source)
        python_library = source.name.lower().startswith(("libpython", "python3")) or source.name == "Python"
        if python_library or (kind == "EXTENSION" and _stdlib_extension(source, relative)):
            native["component"] = "CPython runtime" if python_library else "CPython stdlib extension"
            native["notices"] = report["python"]["notices"] + report["python"]["additional_notices"]
            continue
        package = _dpkg_package(source) if sys.platform.startswith("linux") else None
        if package:
            native["package_provenance"] = package
            native["notices"], missing = _debian_notices(package, destination)
            for reason in missing:
                report["unresolved"].append({"component": name, "source_path": source_text, "reason": reason})
        else:
            installed_notices = _installed_native_notices(source)
            for number, notice in enumerate(installed_notices, 1):
                safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
                native["notices"].append(_copy_notice(notice, destination, Path("Native/Installed") / safe_name / f"{number}-{notice.name}"))
            if not native["notices"] and additional_python_notice and _python_component_in_notice(source.name, additional_python_notice):
                native["notices"] = report["python"]["additional_notices"]
                native["notice_resolution"] = "Explicitly supplied CPython component notice artifact"
            if not native["notices"]:
                report["unresolved"].append({"component": name, "source_path": source_text, "reason": "No installed component-specific native license was located"})
    (destination / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
