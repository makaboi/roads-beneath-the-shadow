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

EXPECTED = json.loads("{\"repository\":\"makaboi/roads-beneath-the-shadow\",\"run_id\":37114790365,\"head_commit\":\"e984f7b02193ffe7da36ede2e9d5dd42cc24b99a\",\"source_tree\":\"1f3f969ea268801e4e673199ad850d4f530fcca9\",\"version\":\"0.7.1\",\"artifacts\":[{\"id\":11271268454,\"name\":\"desktop-macOS-Intel\",\"size_in_bytes\":60484673,\"digest\":\"sha256:a753c11b9fd0fb6ceeb52cf2460d4f6ce3e9faacc89aeaf63ee0c6ae62e19856\"},{\"id\":11270833915,\"name\":\"desktop-Linux-x64\",\"size_in_bytes\":68810186,\"digest\":\"sha256:32c1c54435d8291cda50daa23d16e512f9cca67225ff4da45fbd1d22dc13c3bb\"},{\"id\":11270398040,\"name\":\"desktop-macOS-Apple-Silicon\",\"size_in_bytes\":57887044,\"digest\":\"sha256:3b1a7effce72be0d26dca3edcf3077431348fefc4946149a647c4cd801172afc\"},{\"id\":11270323299,\"name\":\"desktop-Windows-x64\",\"size_in_bytes\":43495204,\"digest\":\"sha256:d40189dea119a921046ef5b64169302380bb663b872043769469b3e6ef9a26ee\"}],\"assets\":[{\"id\":607579614,\"name\":\"Roads-Beneath-the-Shadow-Linux-x64.tar.gz\",\"size\":68921978,\"digest\":\"sha256:f9e90e9d9b33ca012ebb0496149108e8a14974a52480c6e2259bd24d50cb9b57\"},{\"id\":607579608,\"name\":\"Roads-Beneath-the-Shadow-Linux-x64.tar.gz.sha256\",\"size\":108,\"digest\":\"sha256:dc8c15ec905ae2891eb0128586ef265e4ac562f2cb7e963a3b8d4833bf9c5b7f\"},{\"id\":607579606,\"name\":\"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip\",\"size\":58210231,\"digest\":\"sha256:b616895ff5fbf81a622c5122e9dde4c8268455d6559b995e2faf440ee6bbd8f3\"},{\"id\":607579627,\"name\":\"Roads-Beneath-the-Shadow-macOS-Apple-Silicon.zip.sha256\",\"size\":115,\"digest\":\"sha256:9fba1fd51536f9a40afd421f3481f20e7259a17e5633b0f74aca7d5ded712c5d\"},{\"id\":607579628,\"name\":\"Roads-Beneath-the-Shadow-macOS-Intel.zip\",\"size\":60780628,\"digest\":\"sha256:797a11ae7a2dda47fd7b3fa519fe62da814c2fbfb3de16efe40eb83d02a840c1\"},{\"id\":607579632,\"name\":\"Roads-Beneath-the-Shadow-macOS-Intel.zip.sha256\",\"size\":107,\"digest\":\"sha256:65dc5db239b8b5da2eb7ab9bbfedc818f6e85227a33ea32762c891f38cb06440\"},{\"id\":607579610,\"name\":\"Roads-Beneath-the-Shadow-Windows-x64.zip\",\"size\":43700038,\"digest\":\"sha256:81ed71eb961d10524e7a9b012ee3c1b55a602072d8029e194cb8c8f150445c62\"},{\"id\":607579612,\"name\":\"Roads-Beneath-the-Shadow-Windows-x64.zip.sha256\",\"size\":108,\"digest\":\"sha256:f6f1e397420c51280ee57018205642b105dcce93a198b3008c2625b11091a5a0\"}]}")
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

