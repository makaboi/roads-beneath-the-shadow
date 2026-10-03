"""Retain bounded, hash-bound review parts of native preview archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.desktop_release import PLATFORMS, archive_name


# Leave room below 24 MiB for the manifest, QA, checksum and ZIP envelope.
PART_BYTES = 23 * 1024 * 1024
MAX_PARTS = 4
METADATA_BYTES = 64 * 1024
MANIFEST_NAME = "PREVIEW-ARCHIVE-MANIFEST.json"


def metadata_bytes(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Preview metadata must be a regular file")
    with path.open("rb") as source:
        data = source.read(METADATA_BYTES + 1)
    if len(data) > METADATA_BYTES:
        raise ValueError("Preview metadata exceeds its bounded size")
    return data


def prepare_preview_parts(input_dir: Path, output_dir: Path, platform: str, *, part_bytes: int = PART_BYTES,
                          expected_version: str | None = None) -> dict:
    if platform not in PLATFORMS or type(part_bytes) is not int or not 1 <= part_bytes <= PART_BYTES:
        raise ValueError("Invalid preview platform or review-part size")
    archive = input_dir / archive_name(platform)
    info = archive.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= part_bytes * MAX_PARTS:
        raise ValueError("Preview archive must be regular, nonempty and fit at most four review parts")
    checksum_path = archive.with_name(archive.name + ".sha256")
    qa_path = archive.with_name(archive.name + ".qa.json")
    checksum, qa_bytes = metadata_bytes(checksum_path), metadata_bytes(qa_path)
    match = re.fullmatch(rb"([0-9a-f]{64})  " + re.escape(archive.name.encode("ascii")) + rb"\r?\n", checksum)
    if match is None:
        raise ValueError("Preview archive has an invalid checksum sidecar")
    expected = match[1].decode("ascii")
    qa = json.loads(qa_bytes)
    if not isinstance(qa, dict) or not isinstance(qa.get("archive"), dict):
        raise ValueError("Preview QA and its archive metadata must be objects")
    version, commit = qa.get("version"), qa.get("source_commit")
    identity = qa.get("archive", {})
    if (qa.get("platform") != platform or not isinstance(version, str)
            or re.fullmatch(r"\d+\.\d+\.\d+", version) is None
            or not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or expected_version is not None and version != expected_version
            or identity.get("name") != archive.name or identity.get("sha256") != expected
            or type(identity.get("size_bytes")) is not int or identity["size_bytes"] != info.st_size
            or os.environ.get("GITHUB_SHA") not in (None, "", commit)):
        raise ValueError("Preview QA does not match the exact archive/platform/version/source commit")

    # Preserve existing evidence rather than overwriting a previous invocation.
    output_dir.mkdir(parents=True, exist_ok=False)
    parts, whole, offset = [], hashlib.sha256(), 0
    with archive.open("rb") as source:
        for number in range(1, (info.st_size + part_bytes - 1) // part_bytes + 1):
            folder = output_dir / f"part-{number:03d}"
            folder.mkdir()
            name = f"{archive.name}.part-{number:03d}"
            size, digest = 0, hashlib.sha256()
            with (folder / name).open("xb") as target:
                while size < min(part_bytes, info.st_size - offset):
                    data = source.read(min(1024 * 1024, part_bytes - size, info.st_size - offset - size))
                    if not data:
                        raise ValueError("Preview archive changed while preparing review parts")
                    target.write(data); whole.update(data); digest.update(data); size += len(data)
            parts.append({"number": number, "name": name, "offset": offset,
                          "size_bytes": size, "sha256": digest.hexdigest()})
            offset += size
        if source.read(1) or offset != info.st_size or whole.hexdigest() != expected:
            raise ValueError("Preview archive bytes do not match the native checksum/QA")

    manifest = {"schema": 1, "platform": platform, "version": version, "source_commit": commit,
                "archive": {"name": archive.name, "size_bytes": offset, "sha256": whole.hexdigest()},
                "part_bytes_limit": part_bytes, "parts": parts,
                "qa_sha256": hashlib.sha256(qa_bytes).hexdigest(),
                "checksum_sha256": hashlib.sha256(checksum).hexdigest()}
    data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    for part in parts:
        folder = output_dir / f"part-{part['number']:03d}"
        (folder / MANIFEST_NAME).write_bytes(data)
        (folder / qa_path.name).write_bytes(qa_bytes)
        (folder / checksum_path.name).write_bytes(checksum)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    manifest = prepare_preview_parts(args.input_dir, args.output_dir, args.platform, expected_version=args.expected_version)
    print(json.dumps({"archive": manifest["archive"], "review_parts": len(manifest["parts"]),
                      "source_commit": manifest["source_commit"]}))


if __name__ == "__main__":
    main()
