#!/usr/bin/env python3
"""Reproducible local retrieval projection, not a replacement dataset release."""
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/graphics"))
from corpus import search_key, label_name

folder = ROOT / "services/graphics/corpus"
source = folder / "modavis-pod-1.5-orgrec.sqlite"
record = json.loads((folder / "zenodo-record.json").read_text())
entry = next(f for f in record["files"] if f["key"] == source.name)
assert hashlib.md5(source.read_bytes()).hexdigest() == entry["checksum"].split(":")[1], "Zenodo checksum mismatch"
dest = folder / "catalogue.sqlite"
if dest.exists():
    raise SystemExit("Projection already exists. Use a new output directory or deliberately move the old projection first.")
db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
groups = {}
counts = Counter()
query = """SELECT c.*, p.source_record_id,p.source_key,p.evidence_sha256,p.decision_sha256
FROM component c JOIN component_provenance p ON c.component_id=p.component_id
ORDER BY c.label, c.component_id"""
for r in db.execute(query):
    row = dict(r)
    counts[row["component_type"]] += 1
    name = label_name(row["label"])
    key = (name, row["component_type"])
    group = groups.setdefault(key, {"name": name, "type": row["component_type"], "rows": 0, "evidence": []})
    group["rows"] += 1
    if len(group["evidence"]) < 3:
        group["evidence"].append(row)
report = {
    "schema": "modavis-scriptor.modavis-retrieval/v1", "created_at": datetime.now(timezone.utc).isoformat(),
    "dataset": record["metadata"]["title"], "creator": "Dominik Ukolov", "version": "1.5.0",
    "doi": "10.5281/zenodo.22234059", "url": "https://zenodo.org/records/22234059",
    "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_file": source.name, "source_md5": entry["checksum"],
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "input_components": db.execute("SELECT count(*) FROM component").fetchone()[0],
    "joined_components": sum(counts.values()), "component_types": dict(counts), "retrieval_labels": len(groups),
    "projection": "All component types; distinct exact retrieval names with type; row counts and first three evidence rows sorted by original label and component_id. Original labels and provenance in evidence are unmodified.",
    "search_policy": "NFC/casefold/whitespace, trailing pitch/rank split for retrieval only; no diacritic folding, semantic synonyms, frequency prior or automatic replacement.",
    "scope": "Domain corpus, not a same-author corpus and not evidence that this photograph depicts a matched organ.",
    "source_url_limit": "OrgRec provides source_record_id/source_key and hashes, not per-component source URLs. Cite the versioned dataset and identifiers; do not invent external URLs.",
    "importer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
assert report["input_components"] == report["joined_components"]
with sqlite3.connect(dest) as out:
    out.execute("CREATE TABLE labels(id INTEGER PRIMARY KEY, name TEXT NOT NULL, component_type TEXT NOT NULL, search_key TEXT NOT NULL, component_rows INTEGER NOT NULL, evidence_json TEXT NOT NULL)")
    out.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    out.executemany("INSERT INTO labels(name,component_type,search_key,component_rows,evidence_json) VALUES(?,?,?,?,?)", [(g["name"], g["type"], search_key(g["name"]), g["rows"], json.dumps(g["evidence"], ensure_ascii=False)) for g in groups.values()])
    out.execute("CREATE INDEX labels_search ON labels(search_key)")
    out.execute("INSERT INTO metadata VALUES('report',?)", (json.dumps(report, ensure_ascii=False),))
    out.execute("PRAGMA optimize")
report["catalogue_sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
(folder / "import-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
