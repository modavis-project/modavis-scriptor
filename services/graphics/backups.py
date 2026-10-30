"""Consistent managed-data backups, checked transport, and non-overwriting restore."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile

from database import SCHEMA_VERSION, TRIGGERS, connect, normalized_sql, validate_ledger, validate_schema
from evidence import ARTIFACT, CHUNK_SIZE, IntegrityError, artifact_stream, sha256, verified_copy
from storage import artifact_folder, publish_exclusive, store_lock, verified_result, sync_directory, sync_file

SCHEMA = "modavis-scriptor.backup/v1"
ROOT = Path(__file__).parent


def database_report(data):
    database = Path(data) / "graphics.sqlite"
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise IntegrityError("Backup database integrity/reference check failed")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise IntegrityError("Backup database schema is newer than this software")
        validate_ledger(db, version)
        validate_schema(db, version)
        for name, expected in TRIGGERS.items():
            row = db.execute("SELECT sql FROM sqlite_master WHERE name=? AND type='trigger'", (name,)).fetchone()
            if row is None or normalized_sql(row[0]) != normalized_sql(expected):
                raise IntegrityError("Backup review audit triggers are missing or invalid")
        rows = [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY id")]
        counts = {}
        for row in db.execute("SELECT run_id,region_id,version,payload FROM review_events ORDER BY run_id,region_id,version"):
            key = (row[0], row[1])
            counts[key] = counts.get(key, 0) + 1
            if row[2] != counts[key]:
                raise IntegrityError("Review event history has a version gap")
            json.loads(row[3])
        return {"database_schema": version, "runs": len(rows), "review_events": sum(counts.values())}, rows


def managed_files(data):
    """Known evidence is verified; legacy unhashed files keep their historical limitation."""
    data = Path(data)
    report, rows = database_report(data)
    files = {}
    unverified = []
    coverage = {}
    for row in rows:
        run_id = row["id"]
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,120}", run_id):
            raise IntegrityError("Invalid run identifier in backup database")
        if row["status"] not in {"queued", "running", "completed", "failed"}:
            raise IntegrityError("Unrecognized run status in backup database")
        base = data / run_id
        if base.is_symlink():
            raise IntegrityError("Run directories cannot be symbolic links")
        if row["status"] == "completed":
            result = verified_result(data, row, ROOT)
            folder = artifact_folder(data, row)
            prefix = folder.relative_to(data).as_posix()
            for name, digest in {**result["integrity"]["verified_files"], "result.json": row["result_sha256"]}.items():
                files[f"{prefix}/{name}"] = digest
            coverage[run_id] = result["integrity"]["coverage"]
            for name in result["integrity"]["unverified_files"]:
                path = folder / name
                if path.exists():
                    with artifact_stream(folder, name):
                        pass
                    key = f"{prefix}/{name}"
                    files[key] = sha256(path)
                    unverified.append(key)
            if row.get("artifact_path"):
                files[f"{run_id}/original"] = result["image"]["sha256"]
        else:
            if row.get("result_sha256") or row.get("artifact_path"):
                if row["status"] in {"queued", "running"}:
                    guidance = "Restart the current Scriptor service to finish verified publication recovery, then retry backup."
                else:
                    guidance = "Inspect and explicitly recover or resolve this failed publication before backup; restarting alone does not recover failed runs."
                raise IntegrityError(f"Run {run_id} ({row['status']}) has unpublished prepared evidence. {guidance}")
            with artifact_stream(base, "original"):
                pass
            digest = row.get("source_sha256")
            key = f"{run_id}/original"
            files[key] = digest or sha256(base / "original")
            if not digest:
                unverified.append(key)
            coverage[run_id] = "source-checksum" if digest else "legacy-source-unverified"
    report.update({"coverage": coverage, "historically_unverified_files": sorted(unverified)})
    return report, files


def verify_directory(data, expected_files=None):
    report, files = managed_files(data)
    if expected_files is not None:
        if set(expected_files) != {"graphics.sqlite", *files}:
            raise IntegrityError("Backup contains missing or untracked managed files")
        for name, descriptor in expected_files.items():
            path = Path(data) / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size != descriptor["size"] or sha256(path) != descriptor["sha256"]:
                raise IntegrityError(f"Backup transport checksum mismatch: {name}")
    return report, files


def archive_manifest(archive):
    names = archive.namelist()
    if len(names) != len(set(names)) or "backup.json" not in names:
        raise IntegrityError("Backup archive has duplicate entries or no manifest")
    if archive.getinfo("backup.json").file_size > 16 * 1024 * 1024:
        raise IntegrityError("Backup manifest is too large")
    manifest = json.loads(archive.read("backup.json"))
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or not isinstance(manifest.get("files"), dict) or not isinstance(manifest.get("store_report"), dict):
        raise IntegrityError("Unrecognized backup manifest")
    if "graphics.sqlite" not in manifest["files"] or set(names) != {"backup.json", *manifest["files"]}:
        raise IntegrityError("Backup manifest does not match archive entries")
    for name, descriptor in manifest["files"].items():
        if not isinstance(descriptor, dict) or not isinstance(descriptor.get("sha256"), str) or not isinstance(descriptor.get("size"), int) or descriptor["size"] < 0:
            raise IntegrityError("Invalid backup file descriptor")
        parts = PurePosixPath(name).parts
        valid = name == "graphics.sqlite" or (len(parts) in {2, 3} and re.fullmatch(r"[a-zA-Z0-9-]{1,120}", parts[0]) and (len(parts) == 2 or parts[1] == "processed") and (parts[-1] == "result.json" or ARTIFACT.fullmatch(parts[-1])))
        if not valid or name.endswith("/") or "\\" in name or any(part in {".", ".."} for part in parts) or PurePosixPath(name).is_absolute():
            raise IntegrityError("Unsafe path in backup archive")
        if not re.fullmatch(r"[a-f0-9]{64}", descriptor.get("sha256", "")) or descriptor.get("size") != archive.getinfo(name).file_size:
            raise IntegrityError("Invalid backup file descriptor")
        if (archive.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
            raise IntegrityError("Backup archive contains a symbolic link")
    return manifest


def extract_verified(archive_path, target):
    target = Path(target)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = archive_manifest(archive)
        required = sum(value["size"] for value in manifest["files"].values())
        if shutil.disk_usage(target.parent).free < required + 16 * 1024 * 1024:
            raise OSError("Insufficient free space for verified backup restore")
        for name, descriptor in manifest["files"].items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            checksum = hashlib.sha256()
            with archive.open(name) as source, path.open("xb") as output:
                while chunk := source.read(CHUNK_SIZE):
                    checksum.update(chunk)
                    output.write(chunk)
            if checksum.hexdigest() != descriptor["sha256"]:
                raise IntegrityError(f"Backup transport checksum mismatch: {name}")
        report, _ = verify_directory(target, manifest["files"])
        if report != manifest["store_report"]:
            raise IntegrityError("Restored store does not match backup database/evidence report")
        return manifest


def verify_backup(archive_path):
    try:
        with tempfile.TemporaryDirectory(prefix="scriptor-restore-rehearsal-") as temporary:
            return extract_verified(archive_path, Path(temporary))
    except zipfile.BadZipFile as error:
        raise IntegrityError(f"Backup archive is damaged: {error}") from error


def create_backup(data, archive_path, timeout=60):
    if Path(archive_path).is_symlink():
        raise ValueError("Backup target cannot be a symbolic link")
    data, archive_path = Path(data).resolve(), Path(archive_path).resolve()
    if not data.is_dir() or not (data / "graphics.sqlite").is_file() or (data / "graphics.sqlite").is_symlink():
        raise ValueError("Backup source must be an existing Scriptor data directory")
    if archive_path.exists():
        raise FileExistsError(f"Backup target already exists: {archive_path}")
    if data == archive_path or data in archive_path.parents:
        raise ValueError("Save the backup outside the research data directory")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_archive = archive_path.with_name(f".{archive_path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with tempfile.TemporaryDirectory(prefix="scriptor-backup-snapshot-") as temporary:
            snapshot = Path(temporary)
            with store_lock(data, exclusive=True, timeout=timeout), connect(data / "graphics.sqlite") as guard:
                # Also exclude legacy services that do not yet cooperate with file locks.
                guard.execute("BEGIN IMMEDIATE")
                report, files = managed_files(data)
                with closing(sqlite3.connect((data / "graphics.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(snapshot / "graphics.sqlite")) as destination:
                    source.backup(destination)
                descriptors = {}
                for name, digest in files.items():
                    path = snapshot / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as destination:
                        size = verified_copy((data / name).parent, Path(name).name, digest, destination)
                    descriptors[name] = {"sha256": digest, "size": size}
                descriptors["graphics.sqlite"] = {"sha256": sha256(snapshot / "graphics.sqlite"), "size": (snapshot / "graphics.sqlite").stat().st_size}
                restored_report, _ = verify_directory(snapshot, descriptors)
                if restored_report != report:
                    raise IntegrityError("Snapshot changed during backup")
            manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(), "files": descriptors, "store_report": report}
            with zipfile.ZipFile(temporary_archive, "x", zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(descriptors):
                    archive.write(snapshot / name, name)
                archive.writestr("backup.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            verify_backup(temporary_archive)  # Actual extraction, DB checks, and evidence verification.
            sync_file(temporary_archive)
            publish_exclusive(temporary_archive, archive_path)
            return manifest
    finally:
        temporary_archive.unlink(missing_ok=True)


def restore_backup(archive_path, target):
    if Path(target).is_symlink():
        raise ValueError("Restore target cannot be a symbolic link")
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"Restore target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}-restore-{uuid.uuid4().hex}")
    stage.mkdir()
    try:
        manifest = extract_verified(archive_path, stage)
        for path in stage.rglob("*"):
            if path.is_file():
                sync_file(path)
        # File fsync alone does not persist containing directory entries on POSIX.
        for directory in sorted((path for path in stage.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
            sync_directory(directory)
        sync_directory(stage)
        publish_exclusive(stage, target)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Verified Scriptor managed-data backup, restore rehearsal, and non-overwriting restore")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("data", type=Path)
    create.add_argument("archive", type=Path)
    create.add_argument("--timeout", type=float, default=60)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(args.data, args.archive, args.timeout)
        elif args.command == "verify":
            manifest = verify_backup(args.archive)
        else:
            manifest = restore_backup(args.archive, args.target)
        print(json.dumps({"status": "verified", "command": args.command, "report": manifest["store_report"], "files": len(manifest["files"])}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError, zipfile.BadZipFile) as error:
        print(f"Backup operation refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
