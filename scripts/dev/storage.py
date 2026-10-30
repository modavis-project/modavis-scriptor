"""Read-only host storage diagnostics, including nested macOS disk images."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, unquote

GIB = 1024 ** 3


def existing_path(path):
    path = Path(path).expanduser().resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def image_backing_path(path, images):
    """Resolve the longest containing disk-image mount, never its virtual capacity."""
    candidates = []
    path = Path(path).resolve()
    for image in images:
        backing = image.get("image-path")
        if not backing:
            continue
        for entity in image.get("system-entities", []):
            mount = entity.get("mount-point")
            if not mount:
                continue
            try:
                path.relative_to(Path(mount))
            except ValueError:
                continue
            candidates.append((len(Path(mount).parts), Path(backing).expanduser().resolve()))
    return max(candidates, default=(0, None), key=lambda pair: pair[0])[1]


def physical_storage(path, images=None):
    path = existing_path(path)
    if images is None:
        images = []
        if sys.platform == "darwin":
            try:
                result = subprocess.run(["hdiutil", "info", "-plist"], capture_output=True, check=True, timeout=10)
                images = plistlib.loads(result.stdout).get("images", [])
            except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
                pass
    chain, seen = [str(path)], {str(path)}
    for _ in range(8):
        backing = image_backing_path(path, images)
        if backing is None or str(backing) in seen:
            break
        path = existing_path(backing)
        chain.append(str(path))
        seen.add(str(path))
    usage = shutil.disk_usage(path)
    report = {"path": str(path), "backing_chain": chain, "total_gib": round(usage.total / GIB, 2),
              "free_gib": round(usage.free / GIB, 2), "used_percent": round(100 * usage.used / usage.total, 1)}
    if sys.platform == "darwin":
        try:
            device = subprocess.run(["df", "-P", str(path)], capture_output=True, text=True,
                                    check=True, timeout=10).stdout.splitlines()[-1].split()[0]
            result = subprocess.run(["diskutil", "info", "-plist", device], capture_output=True, check=True, timeout=10)
            disk = plistlib.loads(result.stdout)
            report.update(filesystem=disk.get("FilesystemType"), internal=disk.get("Internal"))
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
            pass
    return report


def docker_storage(docker):
    """Inspect the selected endpoint only; never create a container or change context."""
    try:
        data = json.loads(subprocess.run(docker + ["context", "inspect"], capture_output=True, text=True,
                                        check=True, timeout=10).stdout)[0]
        endpoint = data["Endpoints"]["docker"]["Host"]
        report = {"context": data["Name"], "endpoint": endpoint}
        parsed = urlsplit(endpoint)
        if parsed.scheme != "unix":
            return {**report, "note": "Remote backing storage cannot be inferred from this host."}
        socket = Path(unquote(parsed.path))
        path = socket.parent
        if sys.platform == "darwin" and "/.docker/run/" in str(socket):
            # Docker Desktop can keep Docker.raw in a mounted disk image. lsof
            # gives its active path; reading its bytes would be expensive/unneeded.
            result = subprocess.run(["lsof", "-Fn", "-c", "com.docker.virtualization"], capture_output=True,
                                    text=True, timeout=10)
            files = [Path(line[1:]) for line in result.stdout.splitlines()
                     if line.startswith("n") and line.endswith("/Docker.raw")]
            if files:
                path = files[0]
            else:
                return {**report, "note": "Docker Desktop backing path was unavailable; virtual free space is not a host capacity check."}
        elif data["Name"] == "colima-scriptor":
            path = socket.parent.parent
        elif sys.platform.startswith("linux") and str(socket) in {"/var/run/docker.sock", "/run/docker.sock"}:
            root = subprocess.run(docker + ["info", "--format", "{{.DockerRootDir}}"], capture_output=True,
                                  text=True, check=True, timeout=10).stdout.strip()
            if not Path(root).exists():
                return {**report, "note": "The engine's data root is not on this host; backing capacity is unknown."}
            path = Path(root)
        else:
            return {**report, "note": "Socket placement does not establish the engine's backing storage."}
        return {**report, "physical_storage": physical_storage(path)}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as error:
        return {"note": f"Storage inspection unavailable: {type(error).__name__}"}
