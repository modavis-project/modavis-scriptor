#!/usr/bin/env python3
"""Create the optional Python 3.12 environment and verified English/German fast models."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / "services/graphics/.venv"
COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODELS = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "deu": "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d",
}


def main():
    python = shutil.which("python3.12")
    if not python:
        raise SystemExit("Install Python 3.12 first. Docker development does not need a host Python environment.")
    if not shutil.which("tesseract"):
        raise SystemExit("Install Tesseract 5 first (macOS: brew install tesseract).")
    if not (VENV / "bin/python").exists():
        subprocess.run([python, "-m", "venv", str(VENV)], check=True)
    interpreter = str(VENV / "bin/python")
    subprocess.run([interpreter, "-c", "import sys; assert sys.version_info[:2] == (3,12), 'Recreate the venv with Python 3.12'"], check=True)
    subprocess.run([interpreter, "-m", "ensurepip", "--upgrade"], check=True)
    subprocess.run([interpreter, "-m", "pip", "install", "-r", str(ROOT / "services/graphics/requirements.lock")], check=True)
    subprocess.run([interpreter, "-m", "pip", "check"], check=True)
    directory = VENV / "tessdata"
    directory.mkdir(exist_ok=True)
    sources = {}
    for language, expected in MODELS.items():
        destination = directory / (language + ".traineddata")
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/{destination.name}"
        if destination.exists():
            content = destination.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise SystemExit(f"Refusing to replace an unexpected model: {destination}")
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != expected:
                raise SystemExit(f"Upstream checksum mismatch: {language}; no model written")
            destination.write_bytes(content)
        sources[destination.name] = {"url": url, "sha256": expected}
    (directory / "SOURCE.json").write_text(json.dumps({"repository": "https://github.com/tesseract-ocr/tessdata_fast",
        "commit": COMMIT, "license": "Apache-2.0", "files": sources}, indent=2) + "\n")
    print(f"Native environment ready. Set TESSDATA_PREFIX={directory} when launching the native backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
