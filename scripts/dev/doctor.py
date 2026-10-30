#!/usr/bin/env python3
"""Read-only checks for a checkout's Docker or native development prerequisites."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from environment import docker_command, native_environment, native_python, python312
from storage import docker_storage, physical_storage

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", help="check native Python/Tesseract instead of Docker")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args()
    checks = []
    warnings = []
    diagnostics = {"workspace_storage": physical_storage(ROOT)}
    environment = native_environment() if args.native else os.environ.copy()
    managed_models = ROOT / "services/graphics/.venv/tessdata"
    if args.native and managed_models.is_dir():
        environment.setdefault("TESSDATA_PREFIX", str(managed_models))

    def check(label, command, hint, validate=None):
        try:
            process = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
            output = process.stdout.strip()
            passed = process.returncode == 0 and (validate(output) if validate else True)
            detail = output.splitlines()[0] if passed and output else "OK" if passed else hint
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            passed, detail = False, hint
        checks.append({"check": label, "ok": passed, "detail": detail})

    check("Node.js", ["node", "--version"], "Use Node.js 22.23.4 from .nvmrc (see docs/INSTALLATION.md).",
          lambda text: (22, 23, 4) <= tuple(map(int, re.match(r"v(\d+)\.(\d+)\.(\d+)", text).groups())) < (23, 0, 0))
    check("npm", ["npm", "--version"], "Install npm with Node.js.")
    installed = (ROOT / "node_modules/vinext/package.json").is_file()
    checks.append({"check": "Web dependencies", "ok": installed,
                   "detail": "Installed" if installed else "Run npm ci in this checkout."})
    check("Bundled assets", [sys.executable, "scripts/graphics/verify-assets.py"],
          "Bundled fixture, corpus, or model verification failed; run npm run test:assets for details.")
    if args.native:
        interpreter = native_python()
        python = str(interpreter) if interpreter.exists() else python312() or sys.executable
        check("Python 3.12", [python, "-c", "import sys; print(sys.version.split()[0]); sys.exit(sys.version_info[:2] != (3,12))"],
              "Create services/graphics/.venv with Python 3.12 (see docs/INSTALLATION.md).")
        check("Python dependencies", [python, "-c", "import cv2, numpy, PIL, rapidfuzz, fastapi, uvicorn, multipart; print('Imports passed')"],
              "Install services/graphics/requirements.lock in the Python 3.12 virtual environment.")
        check("Tesseract 5", ["tesseract", "--version"], "Install Tesseract 5, including English and German fast models.",
              lambda text: bool(re.match(r"tesseract v?5\.", text)))
        check("System OCR languages", ["tesseract", "--list-langs"], "Install both eng and deu language models.",
              lambda text: {"eng", "deu"} <= set(text.splitlines()))
    else:
        docker = docker_command(environment)
        check("Docker daemon", docker + ["version", "--format", "{{.Server.Version}}"],
              "Start Docker Desktop/Engine and wait until docker version returns a server version.")
        check("Docker Compose", docker + ["compose", "version", "--short"], "Install Docker Compose v2 or newer.")
        check("Compose configuration", docker + ["compose", "config", "--quiet"], "Fix the Compose configuration.")
        diagnostics["docker_storage"] = docker_storage(docker)
        backing = diagnostics["docker_storage"].get("physical_storage", {})
        if backing.get("used_percent", 0) >= 90:
            warnings.append(f"Docker backing filesystem is {backing['used_percent']}% full ({backing['free_gib']} GiB physically free). "
                            "Virtual disk free space is not backing capacity. Use the isolated internal runtime or plan storage maintenance.")
        if len(backing.get("backing_chain", [])) > 1:
            warnings.append("Docker storage is nested in a mounted disk image; inspect its physical backing before heavy builds.")
    workspace_free = diagnostics["workspace_storage"]["free_gib"]
    checks.append({"check": "Workspace physical free space", "ok": workspace_free >= 8,
                   "detail": f"{workspace_free} GiB free; at least 8 GiB required for development artifacts."})
    passed = all(item["ok"] for item in checks)
    if args.json:
        print(json.dumps({"ok": passed, "mode": "native" if args.native else "docker", "checks": checks,
                          "warnings": warnings, "diagnostics": diagnostics}, indent=2))
    else:
        for item in checks:
            print(f"{'PASS' if item['ok'] else 'FAIL'} {item['check']}: {item['detail'] or 'OK'}")
        for warning in warnings:
            print("WARN " + warning)
        print("Ready for development checks." if passed else "Resolve the failed prerequisites above.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
