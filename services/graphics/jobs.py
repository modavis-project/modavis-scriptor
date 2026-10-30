"""Recoverable OCR attempts and atomic, hash-anchored publication."""
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from evidence import IntegrityError, sha256, verified_copy, verify_file, verify
from storage import atomic_json, sync_directory, sync_file, store_lock, verified_result, service_owner, publish_exclusive


def execute(run_id, data, connection, process_image, catalogue, now):
    data = Path(data)
    attempt = uuid.uuid4().hex
    folder = data / run_id
    stage = folder / (".attempt-" + attempt)
    with store_lock(data, timeout=None):
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "queued":
                return
            db.execute("UPDATE runs SET status='running',error=NULL,attempt_id=?,result_sha256=NULL,artifact_path=NULL WHERE id=?", (attempt, run_id))
        try:
            if not row["source_sha256"]:
                raise IntegrityError("No preserved source checksum for this legacy run; re-upload the original image before processing")
            stage.mkdir()
            with (stage / "original").open("xb") as stream:
                verified_copy(folder, "original", row["source_sha256"], stream)
            result = process_image(stage, json.loads(row["config"]), catalogue)
            verify_file(folder, "original", row["source_sha256"])
            verify_file(stage, "original", row["source_sha256"])
            if result["image"]["sha256"] != row["source_sha256"]:
                raise IntegrityError("Processed source checksum conflicts with the preserved upload")
            result["metadata"] = json.loads(row["metadata"])
            result["run_id"] = run_id
            verify(stage, result)
            atomic_json(stage / "result.json", result)
            # Flush generated evidence before the database commits the publication digest.
            for path in stage.iterdir():
                if path.is_file():
                    sync_file(path)
            sync_directory(stage)
            digest = sha256(stage / "result.json")
            with connection() as db:
                db.execute("UPDATE runs SET result_sha256=?,artifact_path='processed' WHERE id=? AND attempt_id=?", (digest, run_id, attempt))
            os.replace(stage, folder / "processed")
            sync_directory(folder)
            with connection() as db:
                db.execute("UPDATE runs SET status='completed',attempt_id=NULL WHERE id=? AND attempt_id=?", (run_id, attempt))
        except Exception as error:
            # Ordinary failures release capacity; a process crash instead leaves running state
            # and its prepared digest for startup recovery. Saved source bytes always remain.
            with connection() as db:
                current = db.execute("SELECT result_sha256 FROM runs WHERE id=?", (run_id,)).fetchone()
                if current and current[0]:
                    db.execute("UPDATE runs SET status='failed',error=? WHERE id=? AND attempt_id=?", (str(error)[:1000], run_id, attempt))
                else:
                    db.execute("UPDATE runs SET status='failed',error=?,attempt_id=NULL WHERE id=? AND attempt_id=?", (str(error)[:1000], run_id, attempt))
            if not current or not current[0]:
                shutil.rmtree(stage, ignore_errors=True)


def recover(data, connection, root):
    """Called by the sole service owner before workers start; never replace completed data."""
    data = Path(data)
    with connection() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM runs WHERE status IN ('queued','running')")]
    for row in rows:
        folder = data / row["id"]
        attempt = row.get("attempt_id")
        stage = folder / (".attempt-" + attempt) if attempt and len(attempt) == 32 and all(c in "0123456789abcdef" for c in attempt) else None
        try:
            if not row.get("source_sha256"):
                raise IntegrityError("No preserved source checksum for this legacy interrupted run; re-upload the original image")
            verify_file(folder, "original", row["source_sha256"])
            if row.get("result_sha256") and row.get("artifact_path") == "processed":
                published = folder / "processed"
                if not published.exists() and stage and stage.is_dir() and not stage.is_symlink():
                    # Validate the prepared directory against the digest anchored before crash.
                    from evidence import verified_bytes, verify
                    result = json.loads(verified_bytes(stage, "result.json", row["result_sha256"]))
                    if result["run_id"] != row["id"] or result["image"]["sha256"] != row["source_sha256"]:
                        raise IntegrityError("Prepared result identity/source mismatch")
                    verify(stage, result)
                    os.replace(stage, published)
                    sync_directory(folder)
                verified_result(data, row, root)
                with connection() as db:
                    db.execute("UPDATE runs SET status='completed',attempt_id=NULL,error=NULL WHERE id=?", (row["id"],))
            else:
                if stage and stage.is_dir() and not stage.is_symlink():
                    shutil.rmtree(stage)
                with connection() as db:
                    db.execute("UPDATE runs SET status='queued',attempt_id=NULL,result_sha256=NULL,artifact_path=NULL,error=NULL WHERE id=?", (row["id"],))
        except (IntegrityError, OSError, ValueError, KeyError) as error:
            with connection() as db:
                if row.get("result_sha256"):
                    db.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (f"Interrupted run recovery refused: {error}"[:1000], row["id"]))
                else:
                    db.execute("UPDATE runs SET status='failed',attempt_id=NULL,error=? WHERE id=?", (f"Interrupted run recovery refused: {error}"[:1000], row["id"]))
    with connection() as db:
        return [r[0] for r in db.execute("SELECT id FROM runs WHERE status='queued'")]


def recover_failed_publication(data, run_id):
    """Explicit stopped-service recovery of one failed, hash-anchored publication."""
    from database import SCHEMA_VERSION, connect, validate_ledger, validate_schema
    from evidence import verified_bytes
    data = Path(data).resolve()
    if not data.is_dir() or not (data / "graphics.sqlite").is_file() or (data / "graphics.sqlite").is_symlink():
        raise ValueError("Recovery requires an existing Scriptor data directory")
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,120}", run_id):
        raise ValueError("Invalid recovery run identifier")
    with service_owner(data), store_lock(data, exclusive=True), connect(data / "graphics.sqlite") as db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise IntegrityError("Use the current service to validate/migrate this store before explicit recovery")
        validate_ledger(db, version)
        validate_schema(db, version)
        record = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if record is None:
            raise IntegrityError(f"Recovery run not found: {run_id}")
        row = dict(record)
        if row["status"] != "failed" or not row["result_sha256"] or row["artifact_path"] != "processed" or not row["source_sha256"]:
            raise IntegrityError(f"Run {run_id} is not a failed prepared publication with preserved source/result checksums")
        folder = data / run_id
        if folder.is_symlink():
            raise IntegrityError("Recovery run directories cannot be symbolic links")
        verify_file(folder, "original", row["source_sha256"])
        published = folder / "processed"
        attempt = row["attempt_id"]
        if published.exists() or published.is_symlink():
            candidate = published
        elif attempt and re.fullmatch(r"[a-f0-9]{32}", attempt):
            candidate = folder / (".attempt-" + attempt)
        else:
            raise IntegrityError(f"Run {run_id} has no retained prepared directory; restore the exact anchored evidence before recovery")
        if not candidate.is_dir() or candidate.is_symlink():
            raise IntegrityError(f"Run {run_id} has missing or unsafe prepared evidence; restore exact anchored bytes before recovery")
        result = json.loads(verified_bytes(candidate, "result.json", row["result_sha256"]))
        if result.get("schema") != "modavis-scriptor.graphics-run/v1" or result.get("run_id") != run_id or result.get("image", {}).get("sha256") != row["source_sha256"]:
            raise IntegrityError(f"Prepared result identity/source does not match run {run_id}")
        if result.get("metadata") != json.loads(row["metadata"]) or result.get("paradata", {}).get("config") != json.loads(row["config"]):
            raise IntegrityError(f"Prepared result metadata/configuration does not match run {run_id}")
        integrity = verify(candidate, result)
        if integrity["coverage"] != "complete":
            raise IntegrityError("Failed publication recovery requires a complete preserved artifact manifest")
        # All refusal conditions above are read-only. Flush only verified owned outputs.
        for name in [*integrity["verified_files"], "result.json"]:
            sync_file(candidate / name)
        sync_directory(candidate)
        if candidate != published:
            publish_exclusive(candidate, published)
        sync_directory(folder)
        db.execute("UPDATE runs SET status='completed',attempt_id=NULL,error=NULL WHERE id=? AND status='failed' AND result_sha256=?", (run_id, row["result_sha256"]))
        return {"run_id": run_id, "status": "completed", "result_sha256": row["result_sha256"], "source_sha256": row["source_sha256"], "artifact_path": "processed"}


def main(argv=None):
    import argparse
    import sqlite3
    import sys
    parser = argparse.ArgumentParser(description="Explicit recovery of one failed prepared Scriptor publication; service must be stopped")
    command = parser.add_subparsers(dest="command", required=True)
    recover_command = command.add_parser("recover-publication")
    recover_command.add_argument("data", type=Path)
    recover_command.add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(recover_failed_publication(args.data, args.run_id), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as error:
        print(f"Publication recovery refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
