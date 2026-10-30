"""Recoverable OCR attempts and atomic, hash-anchored publication."""
import json
import os
import shutil
import uuid
from pathlib import Path

from evidence import IntegrityError, sha256, verified_copy, verify_file, verify
from storage import atomic_json, sync_directory, store_lock, verified_result


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
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
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
                    db.execute("UPDATE runs SET status='failed',attempt_id=NULL,error=? WHERE id=? AND attempt_id=?", (str(error)[:1000], run_id, attempt))
                else:
                    db.execute("UPDATE runs SET status='failed',error=?,attempt_id=NULL WHERE id=? AND attempt_id=?", (str(error)[:1000], run_id, attempt))
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
                db.execute("UPDATE runs SET status='failed',attempt_id=NULL,error=? WHERE id=?", (f"Interrupted run recovery refused: {error}"[:1000], row["id"]))
    with connection() as db:
        return [r[0] for r in db.execute("SELECT id FROM runs WHERE status='queued'")]
