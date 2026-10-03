"""Build deterministic offline fallbacks and exact cmap indices.

Development only: Python plus fonttools==4.61.1. The installed game does not
import FontTools or require the original TTC. Supply the original managed
Noto binaries with --cjk-source and --devanagari-source. Their fingerprints
are recorded in the output index and retained OFL/provenance notice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from fontTools import __version__
from fontTools.ttLib import TTCollection, TTFont


ROOT = Path(__file__).resolve().parents[1]
CJK_SOURCE_SHA256 = "b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a"
DEVA_SOURCE_SHA256 = "79a470365ccb210fa3c7d8d8ff2e005ef9d983cfd067f735a0caf7e15070ca9f"
FONT_NAMES = {
    "regular": "DejaVuSansMono.ttf", "bold": "DejaVuSansMono-Bold.ttf",
    "cjk": "RBSRoadCJK-Regular.otf", "devanagari": "NotoSansDevanagari-Regular.ttf",
}


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(cjk_source: Path, devanagari_source: Path, output: Path) -> dict:
    if __version__ != "4.61.1":
        raise ValueError("Reproducible extraction requires fonttools==4.61.1")
    for path, expected in ((cjk_source, CJK_SOURCE_SHA256), (devanagari_source, DEVA_SOURCE_SHA256)):
        if checksum(path) != expected:
            raise ValueError(f"{path.name}: source fingerprint differs from the documented Noto source")
    output.mkdir(parents=True, exist_ok=True)
    original_assets = ROOT / "roads_beneath_shadow/font_assets"
    if output.resolve() != original_assets.resolve():
        for filename in (FONT_NAMES["regular"], FONT_NAMES["bold"], "LICENSE.txt", "FALLBACK-OFL.txt"):
            shutil.copyfile(original_assets / filename, output / filename)
    collection = TTCollection(cjk_source, lazy=True, recalcTimestamp=False)
    font = collection.fonts[5]  # Noto Sans Mono CJK JP; full Unicode cmap.
    font.recalcTimestamp = False
    replacements = {1: "RBS Road CJK", 2: "Regular",
                    3: "RBSRoadCJK-Regular;2.004;NotoSansMonoCJKjp",
                    4: "RBS Road CJK Regular", 6: "RBSRoadCJK-Regular",
                    16: "RBS Road CJK", 17: "Regular"}
    for record in font["name"].names:
        if record.nameID in replacements:
            record.string = replacements[record.nameID].encode(record.getEncoding())
    cff = font["CFF "].cff
    cff.fontNames[0] = "RBSRoadCJK-Regular"
    cff.topDictIndex[0].FullName = "RBS Road CJK Regular"
    cff.topDictIndex[0].FamilyName = "RBS Road CJK"
    font.save(output / FONT_NAMES["cjk"], reorderTables=True)
    shutil.copyfile(devanagari_source, output / FONT_NAMES["devanagari"])
    entries = {}
    for kind, filename in FONT_NAMES.items():
        path = output / filename
        face = TTFont(path, lazy=True, recalcTimestamp=False)
        points = sorted(face.getBestCmap())
        ranges = []
        for point in points:
            if ranges and point == ranges[-1][1] + 1:
                ranges[-1][1] = point
            else:
                ranges.append([point, point])
        entries[kind] = {"filename": filename, "sha256": checksum(path),
                         "codepoints": len(points), "ranges": ranges}
        face.close()
    collection.close()
    data = {"schema": 1, "generator": f"fonttools {__version__}",
            "sources": {"noto_cjk_ttc_sha256": CJK_SOURCE_SHA256,
                        "noto_devanagari_ttf_sha256": DEVA_SOURCE_SHA256},
            "fonts": entries}
    (output / "fallback-coverage.json").write_bytes(
        (json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cjk-source", type=Path, required=True)
    parser.add_argument("--devanagari-source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=ROOT / "roads_beneath_shadow/font_assets")
    args = parser.parse_args()
    data = build(args.cjk_source, args.devanagari_source, args.output_directory)
    print(json.dumps({kind: {"filename": entry["filename"], "codepoints": entry["codepoints"],
                            "sha256": entry["sha256"]} for kind, entry in data["fonts"].items()}, indent=2))


if __name__ == "__main__":
    main()
