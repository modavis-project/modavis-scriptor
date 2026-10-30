#!/usr/bin/env python3
"""Verified Scriptor managed-data backup, restore rehearsal, and safe restore."""
from pathlib import Path
import sys

service = Path("/app") if Path("/app/backups.py").exists() else Path(__file__).resolve().parents[2] / "services/graphics"
sys.path.insert(0, str(service))
from backups import main

if __name__ == "__main__":
    raise SystemExit(main())
