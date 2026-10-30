#!/usr/bin/env python3
"""Manage Scriptor's isolated macOS Docker VM without switching the global context."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from environment import ROOT
from storage import GIB, physical_storage

SCHEMA = "modavis-scriptor.development-runtime/v1"
PROFILE = "scriptor"
CONTEXT = "colima-scriptor"
HOME = Path.home() / ".modavis-scriptor-runtime"


def owner(home):
    marker = home / ".owner.json"
    expected = {"schema": SCHEMA, "profile": PROFILE, "context": CONTEXT}
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise RuntimeError("This directory belongs to a different runtime; no files were changed.")
    elif home.exists() and any(home.iterdir()):
        raise RuntimeError("Refusing to adopt an unmarked runtime directory.")
    else:
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
        marker.write_text(json.dumps(expected, indent=2) + "\n")
        marker.chmod(0o600)


def environment(home):
    return {**os.environ, "COLIMA_HOME": str(home)}


def run(command, home, timeout=60, capture=False):
    return subprocess.run(command, env=environment(home), check=True, timeout=timeout,
                          capture_output=capture, text=True)


def validate_context(home, required=False):
    result = subprocess.run(["docker", "context", "inspect", CONTEXT], capture_output=True, text=True, timeout=10)
    if result.returncode:
        if required:
            raise RuntimeError("Start the dedicated runtime first: npm run runtime -- start")
        return False
    context = json.loads(result.stdout)[0]
    expected = "unix://" + str(home / PROFILE / "docker.sock")
    if context["Endpoints"]["docker"]["Host"] != expected:
        raise RuntimeError(f"Docker context {CONTEXT} already points to another runtime; refusing to replace it.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=HOME, help="short, local storage path (default: ~/.modavis-scriptor-runtime)")
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start", help="start a separate 4 GiB VM on local storage")
    start.add_argument("--cpus", type=int, default=4)
    start.add_argument("--memory", type=int, default=4, help="GiB")
    start.add_argument("--disk", type=int, default=32, help="data disk GiB")
    commands.add_parser("status", help="inspect runtime and physical backing capacity")
    commands.add_parser("stop", help="stop only Scriptor's VM, preserving its data")
    execute = commands.add_parser("exec", help="run a command with this Docker context, without changing the global default")
    execute.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This optional VM helper is for macOS. Use the native workflow or your existing Docker engine on other systems.")
    home = args.home.expanduser().resolve()
    if len(str(home / "_lima" / ("colima-" + PROFILE) / "ssh.sock.1234567890123456")) >= 104:
        parser.error("Runtime home is too long for a UNIX socket; choose a shorter --home path.")
    if not shutil.which("colima") or not shutil.which("docker"):
        parser.error("Install Colima and the Docker CLI first (macOS: brew install colima docker docker-compose).")
    if args.action == "start":
        owner(home)
    elif not (home / ".owner.json").exists():
        if args.action == "status":
            print(json.dumps({"context": CONTEXT, "profile": None, "ready": False}))
            return 0
        raise RuntimeError("Start the dedicated runtime first: npm run runtime -- start")
    else:
        owner(home)
    validate_context(home, required=args.action in {"exec", "stop"})
    if args.action == "start":
        if not (1 <= args.cpus <= 16 and 2 <= args.memory <= 16 and 16 <= args.disk <= 128):
            parser.error("Use 1–16 CPUs, 2–16 GiB memory and a 16–128 GiB data disk.")
        storage = physical_storage(home)
        if len(storage["backing_chain"]) > 1 or storage["free_gib"] < 16 or storage.get("filesystem") != "apfs":
            raise RuntimeError("Choose direct APFS storage with at least 16 GiB physically free; nested disk images are not suitable.")
        before = run(["docker", "context", "show"], home, capture=True).stdout.strip()
        run(["colima", "start", PROFILE, "--activate=false", "--template=false", "--vm-type", "vz", "--mount-type", "virtiofs",
             "--cpus", str(args.cpus), "--memory", str(args.memory), "--disk", str(args.disk), "--root-disk", "12",
             "--mount", str(ROOT), "--ssh-config=false"], home, timeout=600)
        validate_context(home, required=True)
        run(["docker", "--context", CONTEXT, "version", "--format", "{{.Server.Version}}"], home)
        after = run(["docker", "context", "show"], home, capture=True).stdout.strip()
        print(json.dumps({"ready": True, "context": CONTEXT, "global_context_before": before,
                          "global_context_after": after, "physical_storage": physical_storage(home)}))
    elif args.action == "status":
        result = subprocess.run(["colima", "list", "--json"], env=environment(home), capture_output=True, text=True, timeout=10)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        print(json.dumps({"context": CONTEXT, "profile": next((row for row in rows if row.get("name") == PROFILE), None),
                          "physical_storage": physical_storage(home)}, indent=2))
    elif args.action == "stop":
        run(["colima", "stop", PROFILE], home, timeout=120)
    else:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("Specify a command after exec --")
        env = {**environment(home), "SCRIPTOR_DOCKER_CONTEXT": CONTEXT, "DOCKER_CONTEXT": CONTEXT}
        env.pop("DOCKER_HOST", None)
        os.execvpe(command[0], command, env)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(str(error))
