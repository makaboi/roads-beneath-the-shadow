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

EXPECTED = json.loads('{"repository":"makaboi/roads-beneath-the-shadow","run_id":37118124822,"head_commit":"91a8fed46cd909c6ee99ecb2245a685c99e2a20b","source_tree":"202c0bf37ea84d287b28b130bbcf8dc5326503d1","version":"0.7.2","artifacts":[{"id":11271704376,"name":"desktop-Linux-x64","size_in_bytes":68812492,"digest":"sha256:1fa6fa764f37b936c42c38c8f0420a30be91155cee02cfd4c3b9f48cd6397f7f"},{"id":11272481971,"name":"desktop-Windows-x64","size_in_bytes":43496490,"digest":"sha256:1158bfe031e901ec1040f0cc94db4c2ead527b79d222659b546dca3e61cdc015"},{"id":11271824284,"name":"desktop-macOS-Apple-Silicon","size_in_bytes":57888683,"digest":"sha256:23c3d8dcb8ab5fd233bcd99663e8aed8e4e8a18980e85ee8928c600e6507198f"},{"id":11272312303,"name":"desktop-macOS-Intel","size_in_bytes":60485988,"digest":"sha256:74146ea0b17bd9b30ab9f1762c60bbcb5e448ebf5a42df8f1dd165c405106e49"}],"assets":[{"id":607661701,"name":"Roads-Beneath-the-Shadow-Linux-x64.tar.gz","size":68924215,"digest":"sha256:983e4a78223a2343c0081bc01bced34ae21f2aaf2ea6d0c9e5f0afa9e8f8837c"},{"id":607661696,"name":"Roads-Beneath-the-Shadow-Linux-x64.tar.gz.sha256","size":108,"digest":"sha256:3d25973b602b1f22cad8590f8deea184539cca4d1c1e424610b4586fcc242358"},{"id":607661702,"name":"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip","size":58211742,"digest":"sha256:bddd6b747f7a3294a5da70943c7e73c8f754fa582661c6de4d3ad863cbc34538"},{"id":607661710,"name":"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip.sha256","size":115,"digest":"sha256:b08ce92bf0f5e2d563d7f4b1e95d872ff6cbdfd5b866b26d7ce19dfbf2e57d66"},{"id":607661714,"name":"Roads-Beneath-the-Shadow-macOS-Intel.zip","size":60781928,"digest":"sha256:aa22565cba92981636c5ebcaa4ab1ed6d95f0355193c77ba0ef9e7445f3d9698"},{"id":607661720,"name":"Roads-Beneath-the-Shadow-macOS-Intel.zip.sha256","size":107,"digest":"sha256:161286cbd6fe870f755111b944ab93a0bc7b80d4e1f7376791444b543ff9dc3f"},{"id":607661699,"name":"Roads-Beneath-the-Shadow-Windows-x64.zip","size":43700968,"digest":"sha256:a6a3c3508f15a1858b3485afabe66032cbda63144763fb9a4a957ec7a3f45763"},{"id":607661700,"name":"Roads-Beneath-the-Shadow-Windows-x64.zip.sha256","size":108,"digest":"sha256:be2a016c0e2f176c962f94661869c881eb1734ae096c68099a4111ba629d5633"}]}')
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

