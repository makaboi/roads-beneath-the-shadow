"""Export only retained native QA from one sealed release-build run."""
import argparse
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import shutil
import stat
import tarfile
import zipfile

EXPECTED = json.loads('{"repository":"makaboi/roads-beneath-the-shadow","run_id":37127903810,"head_commit":"ed78b3c7f7a0cd9cec40b64801fa13e3f861afdc","source_tree":"bdd771b1fe3c85d43f65bfbd76e11daef9ae55a2","version":"0.7.4","artifacts":[{"id":11274768702,"name":"desktop-Linux-x64","size_in_bytes":68810402,"digest":"sha256:5b7d3d828530793c90f49711aaa72d529fa9334a295f0ad55c484c3dfc96bf6d"},{"id":11275890619,"name":"desktop-Windows-x64","size_in_bytes":43494647,"digest":"sha256:e459b1180e9acd3fff0065ba2551367dddb85e257f1bd83ad590f741b4265cde"},{"id":11274704015,"name":"desktop-macOS-Apple-Silicon","size_in_bytes":57890114,"digest":"sha256:29ec6d1f15221d85ecec4ba73f23eb0d9f8e563dcb9188124c9160301327d6cd"},{"id":11276280065,"name":"desktop-macOS-Intel","size_in_bytes":60486535,"digest":"sha256:80574d725120be8e4f2812b4daf5ed117944096e52dda3057cad7bf0c2301523"}],"assets":[{"id":607904530,"name":"Roads-Beneath-the-Shadow-Linux-x64.tar.gz","size":68924664,"digest":"sha256:a3d5d7abe888b0beb41922b033f4f698c576b9c2ad996fbf9ef21810bf0464a4"},{"id":607904531,"name":"Roads-Beneath-the-Shadow-Linux-x64.tar.gz.sha256","size":108,"digest":"sha256:8bc07e53f7fd174ec339cfc6be1aea60c83eb369c003586987fe4570d43327d3"},{"id":607904532,"name":"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip","size":58212670,"digest":"sha256:148d2a1bde17b47ee91e8e9b83a3c084c4053994646f079c32a13065b2db3305"},{"id":607904541,"name":"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip.sha256","size":115,"digest":"sha256:b12d898db8460f65af86605f62a45146ea8b88c53a51dc8043dc857b90c08e87"},{"id":607904545,"name":"Roads-Beneath-the-Shadow-macOS-Intel.zip","size":60782949,"digest":"sha256:0426bee6eda62cde3882687c341281e60e5afe719d702594b095f3ceb0387005"},{"id":607904551,"name":"Roads-Beneath-the-Shadow-macOS-Intel.zip.sha256","size":107,"digest":"sha256:fa426ecc564aa84089fec8b50a985b1bcc5a20d09c6f35017a56c1519c5dfdb6"},{"id":607904528,"name":"Roads-Beneath-the-Shadow-Windows-x64.zip","size":43699831,"digest":"sha256:5789d91afa451e84f6d8bbc9a6fc3d3cb57c246cd119cb6fe7e8483803d555b3"},{"id":607904533,"name":"Roads-Beneath-the-Shadow-Windows-x64.zip.sha256","size":108,"digest":"sha256:2ae8dd28024e7fa1de2c82d083bbb0dd4c22253eb91547f9aff1f5297b1602d1"}]}')
RUNTIME = json.loads("{\"images\":54,\"world_maps\":13,\"fonts\":4,\"audio\":10,\"metadata\":2,\"audio_driver\":\"dummy\",\"controller_backend\":\"pygame._sdl2.controller\",\"font_fallbacks\":{\"schema\":1,\"fonts\":{\"DejaVuSansMono.ttf\":{\"codepoints\":3322,\"sha256\":\"54bf827eb99404e8f430c330ad30f063334f637eba0109b6a18d4f566a8e9dd8\"},\"DejaVuSansMono-Bold.ttf\":{\"codepoints\":3261,\"sha256\":\"0d3c03d1b667192f91223660a3163325cf83132662fe4d9f7d6e596bf7a995c2\"},\"RBSRoadCJK-Regular.otf\":{\"codepoints\":44810,\"sha256\":\"16f7cc5bde69baaee723ea9167f6c442f6126b3351fad3ac5471add465c4e5bd\"},\"NotoSansDevanagari-Regular.ttf\":{\"codepoints\":272,\"sha256\":\"79a470365ccb210fa3c7d8d8ff2e005ef9d983cfd067f735a0caf7e15070ca9f\"}}}}")
PACKAGE = "Roads-Beneath-the-Shadow"
QA_LIMIT = 64 * 1024

def require(value, message):
    if not value:
        raise ValueError(message)

def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()

def strict_json(data):
    require(len(data) <= 256 * 1024, "JSON input exceeds bound")
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("Nonfinite JSON")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    require(isinstance(value, dict), "Expected JSON object")
    return value

def strict_equal(actual, expected):
    require(type(actual) is type(expected), "JSON value type differs")
    if isinstance(expected, dict):
        require(set(actual) == set(expected), "JSON object fields differ")
        for key, value in expected.items():
            strict_equal(actual[key], value)
    elif isinstance(expected, list):
        require(len(actual) == len(expected), "JSON array length differs")
        for a, e in zip(actual, expected):
            strict_equal(a, e)
    else:
        require(actual == expected, "JSON value differs")

def validate_metadata(path):
    require(stat.S_ISREG(path.lstat().st_mode) and 0 < path.stat().st_size <= 256 * 1024, "Metadata file exceeds bounded ordinary input")
    data = strict_json(path.read_bytes())
    require(type(data.get("total_count")) is int and data["total_count"] == 4, "Unexpected artifact count")
    artifacts = data.get("artifacts")
    require(isinstance(artifacts, list) and len(artifacts) == 4, "Missing exact artifact set")
    by_id = {a.get("id"): a for a in artifacts if isinstance(a, dict)}
    require(len(by_id) == 4 and set(by_id) == {a["id"] for a in EXPECTED["artifacts"]}, "Artifact IDs differ")
    for expected in EXPECTED["artifacts"]:
        actual = by_id[expected["id"]]
        for key, value in expected.items():
            strict_equal(actual.get(key), value)
        require(actual.get("expired") is False, "Artifact expired")
        require(0 < actual["size_in_bytes"] < 90 * 1024 * 1024, "Artifact size exceeds bound")
        run = actual.get("workflow_run")
        require(isinstance(run, dict), "Missing artifact workflow provenance")
        strict_equal(run.get("id"), EXPECTED["run_id"])
        strict_equal(run.get("head_sha"), EXPECTED["head_commit"])
    return data

def read_inventory(archive):
    name = PACKAGE + "/THIRD-PARTY-INVENTORY.json"
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as source:
            matches = [m for m in source.getmembers() if m.name == name]
            require(len(matches) == 1 and matches[0].isfile() and matches[0].size <= 1024 * 1024, "Invalid archive inventory")
            with source.extractfile(matches[0]) as incoming:
                return incoming.read()
    with zipfile.ZipFile(archive) as source:
        matches = [m for m in source.infolist() if m.filename == name]
        require(len(matches) == 1 and matches[0].file_size <= 1024 * 1024, "Invalid archive inventory")
        return source.read(matches[0])

def export(metadata_path, input_dir, output_dir):
    metadata = validate_metadata(metadata_path)
    require(not output_dir.exists(), "Output directory must be fresh")
    assets = {a["name"]: a for a in EXPECTED["assets"]}
    expected_names = set(assets) | {name + ".qa.json" for name in assets if not name.endswith(".sha256")}
    children = list(input_dir.iterdir())
    require({p.name for p in children} == expected_names and len(children) == 12, "Downloaded artifact members differ")
    for path in children:
        require(stat.S_ISREG(path.lstat().st_mode), "Only ordinary unlinked artifact files are allowed")
    records = []
    qa_files = []
    for name, asset in assets.items():
        path = input_dir / name
        require(path.stat().st_size == asset["size"] and "sha256:" + file_hash(path) == asset["digest"], "Artifact member differs from actual public asset")
    for artifact in sorted(EXPECTED["artifacts"], key=lambda a: a["name"]):
        platform = artifact["name"].removeprefix("desktop-")
        name = PACKAGE + "-" + platform + (".tar.gz" if platform == "Linux-x64" else ".zip")
        archive, qa_path = input_dir / name, input_dir / (name + ".qa.json")
        require(0 < qa_path.stat().st_size <= QA_LIMIT, "QA sidecar exceeds bound")
        raw = qa_path.read_bytes()
        qa = strict_json(raw)
        require(set(qa) == {"platform", "version", "source_commit", "archive", "binary", "extracted_launcher", "third_party"}, "Unexpected QA fields")
        strict_equal(qa["platform"], platform)
        strict_equal(qa["version"], EXPECTED["version"])
        strict_equal(qa["source_commit"], EXPECTED["head_commit"])
        strict_equal(qa["archive"], {"name": name, "sha256": file_hash(archive), "size_bytes": archive.stat().st_size})
        for key, launcher in (("binary", False), ("extracted_launcher", True)):
            report = qa[key]
            fields = {"version", "decoded_assets", "screenshot_size", "seconds", "through_launcher"}
            if platform == "Windows-x64":
                fields |= {"windows_dependency_path", "build_python_environment_cleared"}
            require(isinstance(report, dict) and set(report) == fields, "Native report fields differ")
            strict_equal(report["version"], EXPECTED["version"])
            strict_equal(report["decoded_assets"], RUNTIME)
            strict_equal(report["screenshot_size"], [1200, 900])
            strict_equal(report["through_launcher"], launcher)
            times = report["seconds"]
            require(isinstance(times, dict) and set(times) == {"version_check", "runtime_decode", "asset_check", "pixel_render", "terminal_quit"}, "Native timing checks differ")
            require(all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 90 for x in times.values()), "Native smoke timing is invalid")
            if platform == "Windows-x64":
                require(report["build_python_environment_cleared"] is True, "Windows native smoke retained build Python environment")
                dependency = report["windows_dependency_path"]
                require(isinstance(dependency, str), "Windows native smoke PATH missing")
                paths = dependency.split(";")
                require(len(paths) == 2 and ntpath.isabs(paths[1]) and ntpath.splitdrive(paths[1])[0] and
                        paths[0] == ntpath.join(paths[1], "System32"), "Windows native smoke PATH contains build dependencies")
        for field in qa["binary"]:
            if field not in {"seconds", "through_launcher"}:
                strict_equal(qa["binary"][field], qa["extracted_launcher"][field])
        notices = qa["third_party"]
        require(isinstance(notices, dict) and set(notices) == {"inventory_sha256", "unresolved"} and notices["unresolved"] == [], "Native notices unresolved")
        require(notices["inventory_sha256"] == hashlib.sha256(read_inventory(archive)).hexdigest(), "QA inventory differs from actual public archive")
        checksum = (input_dir / (name + ".sha256")).read_text(encoding="ascii")
        require(checksum == file_hash(archive) + "  " + name + "\n", "Archive checksum content differs")
        qa_files.append((qa_path, raw))
        records.append({"platform": platform, "source_artifact": artifact, "public_archive_asset": assets[name],
                        "public_checksum_asset": assets[name + ".sha256"], "qa_name": qa_path.name,
                        "qa_size_bytes": len(raw), "qa_sha256": hashlib.sha256(raw).hexdigest(),
                        "archive_size_bytes": archive.stat().st_size, "archive_sha256": file_hash(archive),
                        "both_native_runtime_fingerprints_equal": True, "native_inventory_matches_archive": True})
    output_dir.mkdir(parents=True, exist_ok=False)
    for source, raw in qa_files:
        with (output_dir / source.name).open("xb") as target:
            target.write(raw)
    manifest = {"schema": 1, "status": "passed", "repository": EXPECTED["repository"], "source_run_id": EXPECTED["run_id"],
                "source_commit": EXPECTED["head_commit"], "source_tree": EXPECTED["source_tree"], "version": EXPECTED["version"],
                "export_commit": os.environ.get("GITHUB_SHA"), "export_run_id": os.environ.get("GITHUB_RUN_ID"),
                "export_helper_sha256": file_hash(Path(__file__)), "original_metadata_sha256": file_hash(metadata_path),
                "records": records, "original_artifact_metadata": metadata,
                "transport": "Standard actions/download-artifact@v4 with exact IDs/run/repository; wrapper digests retained from GitHub metadata, not independently rehashed here.",
                "native_execution_performed_by_export": False,
                "limits": "Retained CI native QA bound to actual public archive bytes; no new native execution or source/main/tag/release mutation."}
    raw = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    require(len(raw) <= 64 * 1024, "Export manifest exceeds bound")
    with (output_dir / "NATIVE-QA-EXPORT-MANIFEST.json").open("xb") as target:
        target.write(raw)
    print(json.dumps({"status": "passed", "qa_sidecars": 4, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                      "source_run_id": EXPECTED["run_id"], "source_commit": EXPECTED["head_commit"]}))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("metadata", "export"))
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    options = parser.parse_args()
    if options.mode == "metadata":
        validate_metadata(options.metadata)
        print("Exact existing release artifact metadata verified.")
    else:
        require(options.input_dir is not None and options.output_dir is not None, "Export paths required")
        export(options.metadata, options.input_dir, options.output_dir)
if __name__ == "__main__":
    main()

