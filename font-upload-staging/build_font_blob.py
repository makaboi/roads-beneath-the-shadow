"""Create exactly the reviewed renamed CJK face from an immutable Noto TTC."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from fontTools import __version__
from fontTools.ttLib import TTCollection

SOURCE_SHA256 = "b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a"
OUTPUT_SHA256 = "16f7cc5bde69baaee723ea9167f6c442f6126b3351fad3ac5471add465c4e5bd"
OUTPUT_GIT_OID = "8f43e981c836052e0e95b9542d45d42e9d35b64b"
OUTPUT_BYTES = 16424004
UPSTREAM_COMMIT = "523d033d6cb47f4a80c58a35753646f5c3608a78"


def build(source, output, report):
    if __version__ != "4.61.1":
        raise ValueError("The reviewed extraction requires fonttools==4.61.1")
    if output.exists() or report.exists():
        raise FileExistsError("Preserve existing font/provenance evidence")
    with source.open("rb") as incoming:
        source_digest = hashlib.file_digest(incoming, "sha256").hexdigest()
    if source_digest != SOURCE_SHA256:
        raise ValueError("Pinned original TTC source digest differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    collection = TTCollection(source, lazy=True, recalcTimestamp=False)
    try:
        font = collection.fonts[5]
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
        font.save(output, reorderTables=True)
    finally:
        collection.close()
    raw = output.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if len(raw) != OUTPUT_BYTES or checksum != OUTPUT_SHA256 or oid != OUTPUT_GIT_OID:
        raise ValueError("Generated face differs from the exact reviewed source Git blob")
    result = {"schema": 1, "status": "passed", "fonttools_version": __version__,
              "immutable_upstream_commit": UPSTREAM_COMMIT,
              "source_sha256": source_digest, "source_size_bytes": source.stat().st_size,
              "output_sha256": checksum, "output_size_bytes": len(raw), "output_git_oid": oid,
              "source_builder_commit": os.environ.get("GITHUB_SHA"),
              "source_builder_workflow_run": os.environ.get("GITHUB_RUN_ID"),
              "scope": "Reproducible Git asset transport only; no game release, native loadability or gameplay claim."}
    with report.open("x", encoding="utf-8") as outgoing:
        json.dump(result, outgoing, indent=2)
        outgoing.write("\n")
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "output", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    options = parser.parse_args()
    build(options.source, options.output, options.report)
