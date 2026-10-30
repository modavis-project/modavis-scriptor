#!/usr/bin/env python3
"""Recover one failed prepared publication, with the service stopped."""
import argparse
from pathlib import Path
import sys

service = Path("/app") if Path("/app/jobs.py").exists() else Path(__file__).resolve().parents[2] / "services/graphics"
sys.path.insert(0, str(service))
from jobs import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("run_id")
    arguments = parser.parse_args()
    raise SystemExit(main(["recover-publication", str(arguments.data), arguments.run_id]))
