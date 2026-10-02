"""Retain the licenses, corresponding library sources, and actual frozen payload.

Release builds pin pygame-ce; editable source installs retain their own dependency
selection. Network access is used only while preparing a release, never in the
player executable. Downloaded source archives must match the checked-in hashes.
"""

from __future__ import annotations

import fnmatch
import copy
import gzip
import hashlib
import io
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import urllib.request
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "third_party"
INVENTORY_NAME = "THIRD-PARTY-INVENTORY.json"
NOTICES_NAME = "THIRD-PARTY-NOTICES.md"


def digest(path: Path, algorithm: str = "sha256") -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_archive(source: dict, cache: Path) -> Path:
    """Fetch an exact upstream source; an interrupted download is never reused."""
    filename = source["filename"]
    if Path(filename).name != filename:
        raise ValueError("A third-party source filename must be one path component")
    algorithm = "sha256" if "sha256" in source else "sha512"
    expected = source[algorithm]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / filename
    if target.is_file() and digest(target, algorithm) == expected:
        return target
    temporary = target.with_name(target.name + ".download")
    try:
        request = urllib.request.Request(source["url"], headers={"User-Agent": "RBS-release-source-collector/1"})
        with urllib.request.urlopen(request, timeout=90) as incoming, temporary.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if digest(temporary, algorithm) != expected:
            raise ValueError(f"Third-party source checksum mismatch: {filename}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def native_component(path: Path, manifest: dict, platform: str) -> dict | None:
    for component in manifest["components"]:
        if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in component["patterns"]):
            item = {key: component[key] for key in ("id", "version", "license")}
            if platform == "Windows-x64":
                override = manifest.get("windows_components", {}).get(item["id"])
                if override is None:
                    # A Linux/mac source pin is not evidence for a Windows
                    # DLL supplied by a different, legacy prebuilt package.
                    item["version"] = "See exact Windows prebuilt provenance"
                else:
                    item.update(override)
            return item
    return None


def pygame_library_source(original: Path, target: Path) -> dict:
    """Retain exact LGPL implementation source while omitting unused fonts.

    The official sdist also contains independent default/example/test fonts.
    They are absent from our runtime. The two install-data lists are adjusted
    and prominently marked; all other implementation files retain their bytes.
    """
    changes = {
        "setup.py": '"src_py/freesansbold.ttf",',
        "src_py/meson.build": "    'freesansbold.ttf',\n",
    }
    modified = []
    omitted = []
    with tarfile.open(original, "r:gz") as source, target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as output:
                members = source.getmembers()
                source_root = members[0].name.split("/", 1)[0]
                for member in members:
                    relative = member.name.removeprefix(source_root + "/")
                    if relative.lower().endswith(".ttf"):
                        omitted.append(relative)
                        continue
                    if not (member.isfile() or member.isdir()):
                        raise ValueError(f"Unexpected library-source archive member: {member.name}")
                    info = copy.copy(member)
                    info.mtime = 0
                    data = source.extractfile(member).read() if member.isfile() else None
                    if relative in changes:
                        text = data.decode("utf-8")
                        if text.count(changes[relative]) != 1:
                            raise ValueError(f"Unexpected pygame font-data declaration: {relative}")
                        marker = "# Roads desktop source distribution, 2026-10-02: omit the unused default font from install data.\n"
                        text = text.replace(changes[relative], "", 1)
                        if text.startswith("#!"):
                            first, rest = text.split("\n", 1)
                            text = first + "\n" + marker + rest
                        else:
                            text = marker + text
                        data = text.encode("utf-8")
                        info.size = len(data)
                        modified.append(relative)
                    output.addfile(info, io.BytesIO(data) if data is not None else None)
                if set(modified) != set(changes) or not omitted:
                    raise ValueError("The pygame library-source omissions were not established")
                explanation = (
                    "Roads Beneath the Shadow desktop library-source distribution\n"
                    "2026-10-02\n\n"
                    "Derived from the checksum-verified official pygame-ce 2.5.8 source distribution.\n"
                    "All library implementation source files retain their upstream bytes.\n"
                    "Unused independent default/example/test font resources are omitted:\n"
                    + "\n".join(omitted) + "\n\n"
                    "The default-font install-data entry is removed from setup.py and src_py/meson.build;\n"
                    "each changed file carries a dated notice. The game supplies its licensed DejaVu fonts.\n"
                    "The original upstream URL/hash and this archive's hash are in the player inventory.\n"
                ).encode("utf-8")
                notice = tarfile.TarInfo(source_root + "/RBS-SOURCE-CHANGES.txt")
                notice.size, notice.mode, notice.mtime = len(explanation), 0o644, 0
                output.addfile(notice, io.BytesIO(explanation))
    return {"omitted_resources": omitted, "modified_install_data_files": modified, "changes_date": "2026-10-02"}


def retain_windows_liblzma_notice(bundle: Path, destination: Path, runtime: dict, python_version: str, platform: str) -> None:
    """Retain the constituent omitted from Windows' assembled Python license.

    The dependency pin follows the actual build interpreter's tagged sources.
    No compression or database constituent is inferred from unused stdlib files.
    """
    objects = [item for item in runtime["native_libraries"] if (
        item.get("component") == "CPython stdlib extension"
        and PurePosixPath(item["name"].replace("\\", "/")).name.startswith("_lzma.")
        and item["name"].lower().endswith(".pyd")
    )]
    if platform != "Windows-x64" or not objects:
        return

    def retain(url: str, relative: str) -> tuple[dict, bytes]:
        target = destination / "runtime" / "CPython" / "Windows-liblzma" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=90) as incoming:
            data = incoming.read()
        target.write_bytes(data)
        return {"url": url, "path": target.relative_to(bundle).as_posix(), "sha256": digest(target)}, data

    base = f"https://raw.githubusercontent.com/python/cpython/v{python_version}/PCbuild/"
    props, data = retain(base + "python.props", "python.props")
    versions = set(re.findall(r"<lzmaDir\b[^>]*>[^<]*?xz-([0-9][A-Za-z0-9.+_-]*)[\\/]", data.decode("utf-8")))
    if len(versions) != 1:
        raise ValueError("The actual Windows CPython tag has no unambiguous liblzma source pin")
    reference = "xz-" + versions.pop()
    source = f"https://raw.githubusercontent.com/python/cpython-source-deps/{reference}/"
    notice, notice_data = retain(source + "COPYING", "COPYING")
    # Preserve both build declarations establishing this static constituent.
    extension, _ = retain(base + "_lzma.vcxproj", "_lzma.vcxproj")
    library, _ = retain(base + "liblzma.vcxproj", "liblzma.vcxproj")
    runtime["python"]["windows_liblzma"] = {
        "scope": "Constituent of the observed Windows _lzma extension; separate from XZ command-line tools",
        "cpython_reference": "v" + python_version, "source_reference": reference,
        "bundled_objects": [item["name"] for item in objects],
        "license": "Public domain" if b"liblzma is in the public domain" in notice_data else "See the exact retained liblzma COPYING",
        "notice": notice, "build_provenance": [props, extension, library],
    }


def prepare_bundle(bundle: Path, platform: str, analysis_toc: Path) -> dict:
    """Prepare an onedir build for assembly; failures stop public packaging."""
    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    pygame_version = metadata.version("pygame-ce")
    if pygame_version != manifest["pygame_version"]:
        raise ValueError(f"Desktop source notices require pygame-ce {manifest['pygame_version']}, got {pygame_version}")
    if metadata.version("pyinstaller") != "6.22.0":
        raise ValueError("Desktop runtime notices require the pinned PyInstaller 6.22.0")
    internal = bundle / "_internal"
    if not internal.is_dir():
        raise ValueError("A persistent onedir _internal directory is required")
    # The game ships and validates its own DejaVu fonts. pygame's default
    # font is unused in a complete release and has a separate GPL license.
    for font in internal.rglob("freesansbold.ttf"):
        font.unlink()
    destination = bundle / "third-party"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(exist_ok=True)
    license_inventory = json.loads((CATALOG / "license-inventory.json").read_text(encoding="utf-8"))
    for notice in license_inventory["files"]:
        if digest(CATALOG / notice["path"]) != notice["sha256"]:
            raise ValueError(f"Checked-in third-party notice checksum mismatch: {notice['path']}")
    shutil.copytree(CATALOG / "licenses", destination / "licenses", dirs_exist_ok=True)
    shutil.copytree(CATALOG / "pygame-build", destination / "pygame-build", dirs_exist_ok=True)
    shutil.copy2(CATALOG / "manifest.json", destination / "source-manifest.json")
    for provenance in CATALOG.glob("*.json"):
        if provenance.name != "manifest.json":
            shutil.copy2(provenance, destination / provenance.name)
    python_version = ".".join(map(str, sys.version_info[:3]))
    python_notice_url = f"https://raw.githubusercontent.com/python/cpython/v{python_version}/Doc/license.rst"
    python_notice = destination / "runtime" / "CPython" / "UPSTREAM-DEPENDENCY-NOTICES.rst"
    python_notice.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(python_notice_url, timeout=90) as source:
        python_notice.write_bytes(source.read())
    if __package__:
        from .runtime_notices import collect_runtime_notices
    else:
        from runtime_notices import collect_runtime_notices
    previous_notice = os.environ.get("RBS_CPYTHON_NOTICE_SOURCE")
    os.environ["RBS_CPYTHON_NOTICE_SOURCE"] = str(python_notice)
    try:
        runtime = collect_runtime_notices(bundle, analysis_toc, destination / "runtime")
    finally:
        if previous_notice is None:
            os.environ.pop("RBS_CPYTHON_NOTICE_SOURCE", None)
        else:
            os.environ["RBS_CPYTHON_NOTICE_SOURCE"] = previous_notice
    runtime["cpython_upstream_notice"] = {
        "version": python_version, "url": python_notice_url, "path": python_notice.relative_to(bundle).as_posix(),
        "sha256": digest(python_notice),
    }
    retain_windows_liblzma_notice(bundle, destination, runtime, python_version, platform)
    # CPython's documentation includes its incorporated-library notices; also
    # retain the exact linked OpenSSL revision's own license/NOTICE when the
    # build interpreter identifies that revision, including static builds.
    openssl = runtime["python"]["openssl"]
    openssl_sources = openssl.get("upstream_sources", {})
    for key, filename in (("license_url", "LICENSE.txt"), ("notice_url", "NOTICE")):
        if key not in openssl_sources:
            continue
        target = destination / "runtime" / "OpenSSL" / filename
        target.parent.mkdir(exist_ok=True)
        try:
            with urllib.request.urlopen(openssl_sources[key], timeout=90) as source:
                target.write_bytes(source.read())
        except urllib.error.HTTPError as error:
            if key != "notice_url" or error.code != 404:
                raise
            openssl["upstream_notice_absent_at_reference"] = openssl_sources[key]
        else:
            openssl.setdefault("retained_upstream_notices", []).append({
                "url": openssl_sources[key], "path": target.relative_to(bundle).as_posix(), "sha256": digest(target),
            })
    cache = Path(os.environ.get("RBS_THIRD_PARTY_CACHE", str(ROOT / ".third-party-cache")))
    sources = []
    for source in manifest["sources"]:
        if platform not in source["platforms"]:
            continue
        archive = source_archive(source, cache)
        filename = "pygame-ce-2.5.8-library-source.tar.gz" if source["id"] == "pygame-ce" else archive.name
        target = destination / "sources" / filename
        target.parent.mkdir(exist_ok=True)
        transform = pygame_library_source(archive, target) if source["id"] == "pygame-ce" else {}
        if source["id"] != "pygame-ce":
            shutil.copy2(archive, target)
        sources.append({**source, "upstream_sha256": source["sha256"], "upstream_sha512": source["sha512"],
                        "distributed_filename": target.name, "sha512": digest(target, "sha512"),
                        "path": target.relative_to(bundle).as_posix(), "sha256": digest(target),
                        "size_bytes": target.stat().st_size, **transform})
    components = {}
    payload = []
    for path in sorted(internal.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        item = {"path": relative, "sha256": digest(path), "size_bytes": path.stat().st_size}
        component = native_component(path, manifest, platform)
        if component is not None:
            item["component"] = component["id"]
            components[component["id"]] = component
        elif "pygame_ce.libs" in path.parts or ".dylibs" in path.parts:
            raise ValueError(f"No third-party notice provenance for bundled pygame native library: {relative}")
        elif "pygame" in path.parts and path.suffix.lower() in (".so", ".pyd", ".dll"):
            item["component"] = "pygame-ce"
        payload.append(item)
    for source in sources:
        source["bundled_object_paths"] = [item["path"] for item in payload if item.get("component") == source["id"]]
        source["source_scope"] = (
            "Corresponding bundled library source" if source["bundled_object_paths"]
            else "Additional upstream wheel build-source reference; no separate library object is bundled"
        )
    supporting_files = [{"path": path.relative_to(bundle).as_posix(), "sha256": digest(path)}
                        for path in sorted(destination.rglob("*")) if path.is_file() and "sources" not in path.relative_to(destination).parts]
    inventory = {
        "schema_version": 1, "platform": platform, "pygame_ce": pygame_version,
        "pygame_upstream_commit": manifest["pygame_upstream_commit"],
        "packaging": "onedir; shared libraries remain in _internal",
        "components": sorted(components.values(), key=lambda value: value["id"]),
        "source_archives": sources, "runtime": runtime, "payload": payload, "supporting_files": supporting_files,
    }
    (bundle / INVENTORY_NAME).write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    table = "\n".join(f"| {item['id']} | {item['version']} | {item['license']} |" for item in inventory["components"])
    notices = (
        "# Third-party software in this desktop download\n\n"
        f"pygame-ce {pygame_version} is Copyright the pygame contributors and licensed under LGPL-2.1-or-later. "
        "This game uses pygame-ce and the following bundled native libraries. Their licenses apply to those libraries.\n\n"
        "| Library | Upstream version / provenance | License |\n|---|---|---|\n" + table + "\n\n"
        "Exact license texts and copyright notices are in `third-party/licenses/` and `third-party/runtime/`. "
        "The LGPL license is in `third-party/licenses/LGPL-2.1.txt`. Corresponding LGPL library source archives "
        "are included in `third-party/sources/`; their upstream URLs, versions, and hashes are retained in "
        "`third-party/source-manifest.json` and `THIRD-PARTY-INVENTORY.json`. The pygame wheel's unmodified "
        "build scripts are retained in `third-party/pygame-build/`.\n\n"
        "The source inventory identifies each archive's actual bundled objects. Additional upstream build-source "
        "references may be retained even when that separate library object is absent from this platform's download.\n\n"
        "This software is based in part on the work of the Independent JPEG Group. "
        "It uses the FreeType Project under the FreeType License. DejaVu font notices are in `FONT-LICENSE.txt`.\n\n"
        "CPython and the PyInstaller bootloader/runtime retain their own licenses in `third-party/runtime/`; "
        "the PyInstaller bootloader exception is included in its full COPYING text. The inventory records "
        "the actual interpreter, native payload, and source hashes from this platform's build.\n\n"
        "## Library replacement\n\n"
        "Keep the executable and its complete `_internal` folder together. pygame extensions and native shared "
        "libraries are separate files in that folder. You may modify or replace the LGPL-covered libraries for "
        "your own use and reverse engineer this executable for debugging those modifications. This permission "
        "is limited to that purpose and does not change the project's copyright terms. Replacement libraries "
        "must match the operating system, architecture, Python ABI where relevant, and the interfaces expected "
        "by this build; keep a backup of the original folder. The pygame library-source archive omits unused "
        "default/example/test fonts and marks the two adjusted install-data lists; library implementation source is unchanged.\n"
    )
    (bundle / NOTICES_NAME).write_text(notices, encoding="utf-8")
    return inventory


def verify_inventory(bundle: Path) -> dict:
    """Verify every retained runtime file and source after player extraction."""
    bundle = bundle.resolve()
    inventory = json.loads((bundle / INVENTORY_NAME).read_text(encoding="utf-8"))
    if inventory.get("schema_version") != 1 or not isinstance(inventory.get("payload"), list):
        raise ValueError("Invalid third-party payload inventory")
    for item in [*inventory["payload"], *inventory.get("source_archives", []), *inventory.get("supporting_files", [])]:
        raw = item["path"]
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts or "\\" in raw or any(":" in part for part in relative.parts):
            raise ValueError("Third-party inventory path leaves the player folder")
        path = bundle.joinpath(*relative.parts)
        cursor = bundle
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError("Third-party inventory must name regular packaged files, without symbolic links")
        if not path.resolve().is_relative_to(bundle):
            raise ValueError("Third-party inventory path leaves the player folder")
        if not path.is_file() or digest(path) != item["sha256"]:
            raise ValueError(f"The player archive has a missing or altered runtime/source file: {relative}")
    return inventory
