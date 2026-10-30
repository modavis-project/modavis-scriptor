"""Local store coordination and durable publication primitives."""
from contextlib import contextmanager, ExitStack
import errno
import threading
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from evidence import IntegrityError, verified_copy, verified_bytes, verify

_LOCAL = threading.local()


@contextmanager
def file_lock(path, exclusive=True, timeout=60, reentrant=True):
    """POSIX shared locks; Windows byte locks serialize operations conservatively."""
    path = Path(path)
    key = str(path.resolve())
    held = getattr(_LOCAL, "held", {})
    if reentrant and key in held:
        if exclusive and not held[key]:
            raise RuntimeError("Cannot upgrade a shared store lock during an active operation")
        yield
        return
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream, fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout if timeout is not None else float("inf")
        while True:
            try:
                acquire()
                break
            except (BlockingIOError, OSError) as error:
                if time.monotonic() >= deadline:
                    raise TimeoutError("The data store is busy; retry after processing or backup completes") from error
                time.sleep(.05)
        held[key] = exclusive
        _LOCAL.held = held
        try:
            yield
        finally:
            del held[key]
            release()


@contextmanager
def store_lock(data, exclusive=False, timeout=60):
    """Cooperate across service and backup processes without locking read-only responses."""
    data = Path(data)
    data.mkdir(parents=True, exist_ok=True)
    with file_lock(data / ".operations.lock", exclusive=exclusive, timeout=timeout):
        yield


@contextmanager
def service_owner(data):
    with ExitStack() as stack:
        try:
            stack.enter_context(file_lock(Path(data) / ".service.lock", timeout=0, reentrant=False))
        except TimeoutError as error:
            raise RuntimeError("Another Scriptor service already owns this data directory") from error
        yield


def sync_directory(path):
    if os.name == "nt":
        return  # Windows does not expose directory fsync through Python's file API.
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def artifact_folder(data, row):
    base = Path(data) / row["id"]
    layout = row.get("artifact_path")
    if layout not in {None, "processed"}:
        raise IntegrityError("Unrecognized evidence layout")
    folder = base / layout if layout else base
    if base.is_symlink() or folder.is_symlink():
        raise IntegrityError("Evidence directories cannot be symbolic links")
    return folder


def verified_result(data, row, root):
    folder = artifact_folder(data, row)
    result = json.loads(verified_bytes(folder, "result.json", row["result_sha256"]))
    if result["run_id"] != row["id"]:
        raise IntegrityError("Immutable result run identifier mismatch")
    trusted = None
    if row["id"] == "example-organ-stops-v1":
        manifest = json.loads((Path(root) / "example/seed-manifest.json").read_text(encoding="utf-8"))
        if manifest["run_id"] == row["id"] and manifest["files"]["result.json"] == row["result_sha256"]:
            trusted = manifest["files"]
    integrity = verify(folder, result, trusted)
    digest = result["image"]["sha256"]
    if row.get("source_sha256") is not None and row["source_sha256"] != digest:
        raise IntegrityError("Preserved upload checksum conflicts with immutable result")
    if row.get("artifact_path"):
        from evidence import verify_file
        verify_file(Path(data) / row["id"], "original", digest)
    result["integrity"] = integrity
    return result


def admission_folder(data, run_id):
    folder = Path(data) / run_id
    folder.mkdir()
    atomic_json(folder / ".admission.json", {"run_id": run_id})
    sync_directory(data)
    return folder


def clear_abandoned_admissions(data, known_ids):
    """Only delete newly managed, explicitly marked reservations absent from SQLite."""
    for folder in Path(data).iterdir():
        if not folder.is_dir() or folder.is_symlink() or len(folder.name) != 32:
            continue
        marker = folder / ".admission.json"
        if not marker.is_file() or marker.is_symlink():
            continue
        try:
            managed = json.loads(marker.read_text(encoding="utf-8")) == {"run_id": folder.name}
        except (OSError, ValueError):
            managed = False
        if managed and folder.name not in known_ids and all(c in "0123456789abcdef" for c in folder.name):
            shutil.rmtree(folder)
        elif managed and folder.name in known_ids:
            marker.unlink()


def publish_exclusive(source, target):
    """Atomically publish without replacing an existing archive or restore directory."""
    source, target = Path(source), Path(target)
    if os.name == "nt":
        os.rename(source, target)  # Windows rename refuses an existing destination.
    else:
        import ctypes
        import sys
        library = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            status = library.renamex_np(os.fsencode(source), os.fsencode(target), 0x4)  # RENAME_EXCL
        elif hasattr(library, "renameat2"):
            status = library.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
        else:
            raise RuntimeError("Atomic non-overwriting publication is unavailable on this platform")
        if status:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))
    sync_directory(target.parent)
