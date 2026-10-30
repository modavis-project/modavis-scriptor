"""Shared host paths and explicit runtime selection for development commands."""
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]


def native_python(root=ROOT):
    return root / "services/graphics/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def python312():
    if sys.version_info[:2] == (3, 12):
        return sys.executable
    return shutil.which("python3.12")


def native_environment(root=ROOT, base=None):
    environment = dict(os.environ if base is None else base)
    environment.setdefault("PYTHONUTF8", "1")
    models = root / "services/graphics/.venv/tessdata"
    if models.is_dir():
        environment.setdefault("TESSDATA_PREFIX", str(models))
    return environment


def docker_command(environment=None):
    environment = os.environ if environment is None else environment
    context = environment.get("SCRIPTOR_DOCKER_CONTEXT")
    return ["docker", "--context", context] if context else ["docker"]
