#!/usr/bin/env python3
"""Copy a completed example from a local container and record file fixity."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("container", help="Container holding the completed example")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
destination = root / "services/graphics/example/processed"
if destination.exists():
    raise SystemExit("The frozen example already exists; preserve it before replacing it.")
destination.mkdir()
subprocess.run(["docker", "cp", f"{args.container}:/data/example-organ-stops-v1/.", str(destination)], check=True)
result = json.loads((destination / "result.json").read_text())
assert result["run_id"] == "example-organ-stops-v1"
manifest = {
    "run_id": result["run_id"],
    "schema": "modavis-scriptor.frozen-graphics-example/v1",
    "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir()) if p.is_file()},
    "note": "Completed OCR result without human review events. Reprocessing creates a new run.",
}
(destination.parent / "seed-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"files": len(manifest["files"]), "result_sha256": manifest["files"]["result.json"]}))
