#!/usr/bin/env python3
"""Verify committed evidence without importing the service or writing research data."""
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GRAPHICS = ROOT / "services/graphics"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(path, algorithm="sha256"):
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def main():
    example = GRAPHICS / "example"
    snapshot = example / "processed"
    manifest = json.loads((example / "seed-manifest.json").read_text())
    require(manifest["schema"] == "modavis-scriptor.frozen-graphics-example/v1", "Unknown fixture schema")
    require(set(manifest["files"]) == {p.name for p in snapshot.iterdir() if p.is_file()}, "Fixture file list differs from manifest")
    for name, expected in manifest["files"].items():
        require(Path(name).name == name, f"Unsafe fixture filename: {name}")
        require(digest(snapshot / name) == expected, f"Fixture checksum mismatch: {name}")

    result = json.loads((snapshot / "result.json").read_text())
    require(result["run_id"] == manifest["run_id"], "Fixture run identifier mismatch")
    require(result["schema"] == "modavis-scriptor.graphics-run/v1", "Unknown result schema")
    require(len(result["regions"]) == 21, "Expected 21 frozen regions")
    require(digest(snapshot / "original") == result["image"]["sha256"], "Original checksum mismatch")
    require(digest(snapshot / "image.png") == result["image"]["normalized_sha256"], "Normalized-image checksum mismatch")
    require(digest(example / "Organ-stops.jpg") == digest(snapshot / "original"), "Example source differs from frozen original")
    source = json.loads((example / "source.json").read_text())
    require(digest(example / "Organ-stops.jpg", "sha1") == source["wikimedia_sha1"], "Photo attribution checksum mismatch")

    # These snapshots are historical evidence. New service code must not replace them.
    for name, expected in result["paradata"]["source_code_sha256"].items():
        require(Path(name).name == name, f"Unsafe source snapshot filename: {name}")
        require(digest(snapshot / f"source-{name}") == expected, f"Historical source checksum mismatch: {name}")
    for name, expected in result["paradata"]["model_sha256"].items():
        if name.startswith("best/"):
            require(digest(GRAPHICS / "models" / name) == expected, f"Bundled model checksum mismatch: {name}")

    corpus = GRAPHICS / "corpus"
    report = json.loads((corpus / "import-report.json").read_text())
    require(digest(corpus / "catalogue.sqlite") == report["catalogue_sha256"], "Corpus checksum mismatch")
    require(digest(ROOT / "scripts/graphics/import-modavis.py") == report["importer_sha256"], "Importer checksum differs from recorded projection")
    with sqlite3.connect((corpus / "catalogue.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
        require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "Corpus SQLite integrity failure")
        require(db.execute("SELECT count(*) FROM labels").fetchone()[0] == report["retrieval_labels"], "Corpus label count mismatch")
        counts = dict(db.execute("SELECT component_type,sum(component_rows) FROM labels GROUP BY component_type"))
        require(counts == report["component_types"], "Corpus component counts mismatch")
        require(sum(counts.values()) == report["input_components"] == report["joined_components"], "Corpus provenance row count mismatch")
        for evidence, count in db.execute("SELECT evidence_json,component_rows FROM labels"):
            require(1 <= len(json.loads(evidence)) <= min(3, count), "Invalid corpus evidence group")
    print(json.dumps({"status": "passed", "fixture_files": len(manifest["files"]), "labels": report["retrieval_labels"], "components": report["input_components"]}))


if __name__ == "__main__":
    main()
