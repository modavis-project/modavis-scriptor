#!/usr/bin/env python3
"""Integrity/migration regressions using only temporary databases and a private API process.

Run with PYTHONPATH=services/graphics (or /app inside the graphics image).
No existing API, research volume, Tesseract process, or frozen fixture is modified.
"""
import asyncio
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import threading

from database import SCHEMA_VERSION, connect, migrate
from evidence import build_manifest, sha256
from pipeline import tessdata_directory

SERVICE = Path(importlib.util.find_spec("app").origin).parent
LEGACY = """
CREATE TABLE runs(id TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,metadata TEXT NOT NULL,config TEXT NOT NULL,parent_id TEXT,error TEXT,result_sha256 TEXT);
CREATE TABLE review_events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),region_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,region_id,version));
CREATE INDEX review_lookup ON review_events(run_id,region_id,version);
CREATE TRIGGER review_no_update BEFORE UPDATE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER review_no_delete BEFORE DELETE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
"""


class Migrations(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="scriptor-migration-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "test.sqlite"

    def test_empty_initialization_and_idempotency(self):
        with connect(self.path) as db:
            migrate(db)
            first = list(db.execute("SELECT * FROM schema_migrations"))
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual([r[0] for r in first], list(range(1, SCHEMA_VERSION + 1)))
            self.assertIn("source_sha256", [r[1] for r in db.execute("PRAGMA table_info(runs)")])
            migrate(db)
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM schema_migrations")], [tuple(r) for r in first])
            self.assertEqual(len(list(db.execute("PRAGMA foreign_key_check"))), 0)

    def test_legacy_adoption_preserves_events_and_append_only_triggers(self):
        with connect(self.path) as db:
            db.executescript(LEGACY)
            db.execute("INSERT INTO runs VALUES('a','Title','Project','completed','date','{}','{}',NULL,NULL,'digest')")
            for version in (1, 2):
                db.execute("INSERT INTO review_events VALUES(?,?,?,?,?,?)", (version, "a", "r001", version, '{"rationale":"preserved literal"}', "date"))
        with connect(self.path) as db:
            before = [tuple(r) for r in db.execute("SELECT * FROM review_events ORDER BY id")]
            triggers = [tuple(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")]
            migrate(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertIsNone(db.execute("SELECT source_sha256 FROM runs WHERE id='a'").fetchone()[0])
            self.assertEqual(before, [tuple(r) for r in db.execute("SELECT * FROM review_events ORDER BY id")])
            self.assertEqual(triggers, [tuple(r) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")])
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute("UPDATE review_events SET payload='changed' WHERE id=1")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute("DELETE FROM review_events WHERE id=1")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO review_events VALUES(3,'a','r001',2,'{}','date')")
            self.assertEqual(db.execute("SELECT count(*) FROM review_events").fetchone()[0], 2)

    def test_concurrent_initialization_and_upgrade_use_consistent_schema(self):
        for initial_version in (0, 1):
            path = Path(self.temporary.name) / f"concurrent-{initial_version}.sqlite"
            if initial_version == 1:
                with connect(path) as db:
                    db.executescript(LEGACY)
                    db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)")
                    db.execute("INSERT INTO schema_migrations VALUES(1,'preserved')")
                    db.execute("PRAGMA user_version=1")
            barrier = threading.Barrier(5)
            def initialize(_):
                with connect(path) as db:
                    barrier.wait(timeout=5)
                    migrate(db)
                    return db.execute("PRAGMA user_version").fetchone()[0]
            with ThreadPoolExecutor(max_workers=5) as workers:
                self.assertEqual(list(workers.map(initialize, range(5))), [SCHEMA_VERSION] * 5)

    def test_version_one_upgrade_preserves_rows_and_migration_history(self):
        with connect(self.path) as db:
            db.executescript(LEGACY)
            db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)")
            db.execute("INSERT INTO schema_migrations VALUES(1,'original date')")
            db.execute("PRAGMA user_version=1")
            db.execute("INSERT INTO runs VALUES('a','Title','Project','failed','date','{}','{}',NULL,'Old failure',NULL)")
            db.execute("INSERT INTO review_events VALUES(1,'a','r001',1,'{}','date')")
        with connect(self.path) as db:
            migrate(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(db.execute("SELECT applied_at FROM schema_migrations WHERE version=1").fetchone()[0], "original date")
            self.assertEqual(tuple(db.execute("SELECT status,error,source_sha256 FROM runs WHERE id='a'").fetchone()), ("failed", "Old failure", None))
            self.assertEqual(db.execute("SELECT count(*) FROM review_events").fetchone()[0], 1)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                db.execute("DELETE FROM review_events")

    def test_newer_database_is_unchanged(self):
        with connect(self.path) as db:
            db.execute("CREATE TABLE future_schema(value TEXT)")
            db.execute("INSERT INTO future_schema VALUES('preserve')")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION+1}")
        before = self.path.read_bytes()
        with connect(self.path) as db:
            with self.assertRaisesRegex(RuntimeError, "newer"):
                migrate(db)
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_legacy_schema_refuses_without_partial_migration(self):
        with connect(self.path) as db:
            db.execute("CREATE TABLE runs(secret TEXT)")
            db.execute("INSERT INTO runs VALUES('preserve')")
        before = self.path.read_bytes()
        with connect(self.path) as db:
            with self.assertRaisesRegex(RuntimeError, "Unrecognized"):
                migrate(db)
        self.assertEqual(before, self.path.read_bytes())

    def test_existing_version_without_migration_ledger_is_rejected(self):
        with connect(self.path) as db:
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            with self.assertRaisesRegex(RuntimeError, "ledger"):
                migrate(db)

    def test_legacy_column_definition_mismatch_is_rejected(self):
        with connect(self.path) as db:
            db.executescript(LEGACY.replace("title TEXT NOT NULL", "title INTEGER NOT NULL"))
            with self.assertRaisesRegex(RuntimeError, "definition"):
                migrate(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_failed_migration_rolls_back(self):
        with connect(self.path) as db:
            with patch("database.BASELINE", ["CREATE TABLE partial(value TEXT)", "INVALID SQL"]):
                with self.assertRaises(sqlite3.OperationalError):
                    migrate(db)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(list(db.execute("SELECT name FROM sqlite_master WHERE type='table'")), [])

    def test_native_tessdata_location_uses_executable_report(self):
        with patch("pipeline.subprocess.run") as command:
            command.return_value.stdout = f'List of available languages in "{self.temporary.name}/" (2):\ndeu\neng\n'
            command.return_value.stderr = ""
            self.assertEqual(tessdata_directory(), Path(self.temporary.name))
        with patch("pipeline.subprocess.run") as command:
            command.return_value.stdout = "unexpected output"
            command.return_value.stderr = ""
            with self.assertRaisesRegex(RuntimeError, "active tessdata"):
                tessdata_directory()


class FailedRunRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="scriptor-recovery-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        with patch.dict(os.environ, {"GRAPHICS_DATA": str(Path(cls.temporary.name) / "data")}):
            cls.api = importlib.import_module("app")
        with cls.api.connection() as db:
            migrate(db)
        cls.addClassCleanup(cls.api.POOL.shutdown, wait=True)

    def setUp(self):
        self.api.DATA = Path(self.temporary.name) / uuid.uuid4().hex
        self.api.DATA.mkdir()
        with self.api.connection() as db:
            migrate(db)

    def make_run(self, status="failed", digest=True):
        run_id = uuid.uuid4().hex
        folder = self.api.DATA / run_id
        folder.mkdir()
        original = b"unchanged uploaded source bytes"
        (folder / "original").write_bytes(original)
        source_digest = hashlib.sha256(original).hexdigest() if digest else None
        with self.api.connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,error,source_sha256) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, "Retry", "Disposable", status, "date", "{}", self.api.Config().model_dump_json(), "Original processing failure", source_digest))
        return run_id, folder, original, source_digest

    def test_concurrent_upload_and_retry_share_atomic_queue_capacity(self):
        from PIL import Image
        from starlette.datastructures import UploadFile
        for _ in range(9):
            self.make_run(status="queued")
        parent, parent_folder, original, _ = self.make_run()
        image = io.BytesIO()
        Image.new("RGB", (3, 3), "white").save(image, "PNG")
        request_bytes = image.getvalue()
        barrier = threading.Barrier(2)
        admissions = []
        real_admit = self.api.admit_run
        def simultaneous_admission(*args):
            admissions.append((args[0], args[1]))
            barrier.wait(timeout=5)
            return real_admit(*args)
        def upload():
            source = UploadFile(filename="tiny.png", file=io.BytesIO(request_bytes))
            return asyncio.run(self.api.create_run(file=source, title="Concurrent upload", project="Disposable", config="{}", metadata="{}"))
        def retry():
            return self.api.rerun(parent, self.api.Config())
        def attempt(operation):
            try:
                return 202, operation()
            except self.api.HTTPException as error:
                return error.status_code, None
        with patch.object(self.api.POOL, "submit") as submit, patch.object(self.api, "admit_run", side_effect=simultaneous_admission):
            with ThreadPoolExecutor(max_workers=2) as workers:
                results = list(workers.map(attempt, (upload, retry)))
            self.assertEqual(sorted(status for status, _ in results), [202, 429])
            self.assertEqual(submit.call_count, 1)
        with self.api.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0], 10)
            existing = {r[0] for r in db.execute("SELECT id FROM runs")}
        self.assertEqual(len(admissions), 2)
        for run_id, folder in admissions:
            self.assertEqual(folder.exists(), run_id in existing)
        self.assertEqual((parent_folder / "original").read_bytes(), original)

    def test_failed_queue_insert_cleans_only_new_folder(self):
        parent, parent_folder, original, _ = self.make_run()
        run_id = uuid.uuid4().hex
        folder = self.api.DATA / run_id
        folder.mkdir()
        (folder / "original").write_bytes(b"new request bytes")
        with self.assertRaises(sqlite3.IntegrityError):
            self.api.admit_run(run_id, folder, "Title", "Project", "{}", None, "0" * 64, parent)
        self.assertFalse(folder.exists())
        self.assertEqual((parent_folder / "original").read_bytes(), original)
        with self.api.connection() as db:
            self.assertIsNone(db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone())

    def test_failed_run_retry_preserves_original_digest_and_parent(self):
        run_id, folder, original, digest = self.make_run()
        with patch.object(self.api.POOL, "submit") as submit:
            child = self.api.rerun(run_id, self.api.Config())["id"]
        submit.assert_called_once_with(self.api.execute, child)
        self.assertEqual((self.api.DATA / child / "original").read_bytes(), original)
        row = self.api.run_record(child)
        self.assertEqual((row["status"], row["parent_id"], row["source_sha256"]), ("queued", run_id, digest))
        self.assertEqual(self.api.run_record(run_id)["status"], "failed")

    def test_failed_retry_rejects_changed_or_missing_original(self):
        for operation in ("modify", "remove"):
            run_id, folder, original, _ = self.make_run()
            if operation == "modify":
                (folder / "original").write_bytes(original + b"changed")
            else:
                (folder / "original").unlink()
            with patch.object(self.api.POOL, "submit") as submit:
                with self.assertRaises(self.api.HTTPException) as error:
                    self.api.rerun(run_id, self.api.Config())
                self.assertEqual(error.exception.status_code, 409)
                submit.assert_not_called()

    def test_old_failed_without_digest_requires_reupload(self):
        run_id, _, _, _ = self.make_run(digest=False)
        with self.assertRaises(self.api.HTTPException) as error:
            self.api.rerun(run_id, self.api.Config())
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("re-upload", error.exception.detail)
        self.assertIsNone(self.api.run_record(run_id)["source_sha256"])

    def test_pending_retry_requires_wait(self):
        for status in ("queued", "running"):
            run_id, _, _, _ = self.make_run(status=status)
            with self.assertRaises(self.api.HTTPException) as error:
                self.api.rerun(run_id, self.api.Config())
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("wait", error.exception.detail)

    def test_upload_anchors_request_bytes_before_queueing(self):
        from PIL import Image
        from starlette.datastructures import UploadFile
        image = io.BytesIO()
        Image.new("RGB", (3, 3), "white").save(image, "PNG")
        body = image.getvalue()
        upload = UploadFile(filename="tiny.png", file=io.BytesIO(body))
        with patch.object(self.api.POOL, "submit"):
            result = asyncio.run(self.api.create_run(file=upload, title="Isolated upload", project="Disposable", config="{}", metadata="{}"))
        self.assertEqual(self.api.run_record(result["id"])["source_sha256"], hashlib.sha256(body).hexdigest())

    def test_execute_rejects_changed_source_before_any_ocr(self):
        run_id, folder, original, _ = self.make_run(status="queued")
        (folder / "original").write_bytes(original + b"changed")
        with patch.object(self.api, "process_image") as process:
            self.api.execute(run_id)
            process.assert_not_called()
        row = self.api.run_record(run_id)
        self.assertEqual(row["status"], "failed")
        self.assertIn("checksum mismatch", row["error"])
        self.assertFalse((folder / "result.json").exists())

    def test_execute_rejects_source_changed_during_processing(self):
        run_id, folder, original, digest = self.make_run(status="queued")
        def changed_source(*_args):
            (folder / "original").write_bytes(original + b"changed")
            return {"image": {"sha256": digest}}
        with patch.object(self.api, "process_image", side_effect=changed_source):
            self.api.execute(run_id)
        self.assertEqual(self.api.run_record(run_id)["status"], "failed")
        self.assertFalse((folder / "result.json").exists())

    def test_execute_rejects_processed_source_digest_conflict(self):
        run_id, folder, _, _ = self.make_run(status="queued")
        with patch.object(self.api, "process_image", return_value={"image": {"sha256": "0" * 64}}):
            self.api.execute(run_id)
        self.assertEqual(self.api.run_record(run_id)["status"], "failed")
        self.assertFalse((folder / "result.json").exists())


class IntegrityAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="scriptor-integrity-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.data = Path(cls.temporary.name) / "data"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        log = (Path(cls.temporary.name) / "server.log").open("wb")
        cls.addClassCleanup(log.close)
        env = {**os.environ, "GRAPHICS_DATA": str(cls.data), "SCRIPTOR_DISPOSABLE_TEST": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        cls.server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(200):
            if cls.server.poll() is not None:
                raise RuntimeError((Path(cls.temporary.name) / "server.log").read_text(encoding="utf-8"))
            try:
                status, body = cls.request("/health")
                if status == 200:
                    assert json.loads(body)["disposable_test_instance"] is True
                    break
            except OSError:
                pass
            time.sleep(.1)
        else:
            raise RuntimeError("Isolated integrity test API did not become ready")
        cls.seed = "example-organ-stops-v1"
        cls.seed_result = json.loads((cls.data / cls.seed / "result.json").read_text(encoding="utf-8"))

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def request(cls, path, method="GET", payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(cls.base + path, data=body, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def insert_run(self, result):
        run_id = uuid.uuid4().hex
        folder = self.data / run_id
        shutil.copytree(self.data / self.seed, folder)
        result = json.loads(json.dumps(result))
        result["run_id"] = run_id
        return run_id, folder, result

    def save_run(self, run_id, folder, result):
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with connect(self.data / "graphics.sqlite") as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,result_sha256) VALUES(?,?,?,?,?,?,?,?)", (run_id, "Integrity test", "Disposable", "completed", "date", json.dumps(result["metadata"]), json.dumps(result["paradata"]["config"]), sha256(folder / "result.json")))

    def assert_rejected_everywhere(self, run_id):
        paths = [(f"/runs/{run_id}", "GET", None), (f"/runs/{run_id}/image", "GET", None), (f"/runs/{run_id}/regions/r003/crop", "GET", None),
                 (f"/runs/{run_id}/regions/r003/review", "PATCH", {"action": "retain", "reviewer": "Isolated QA", "rationale": "Image-based test rationale", "expected_version": 0}),
                 (f"/runs/{run_id}/rerun", "POST", {})]
        paths += [(f"/runs/{run_id}/export?format={fmt}", "GET", None) for fmt in ("json", "markdown", "raw-markdown", "csv", "bundle")]
        for path, method, payload in paths:
            with self.subTest(path=path):
                code, body = self.request(path, method, payload)
                self.assertEqual(code, 409, (path, body[:300]))
        with connect(self.data / "graphics.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM review_events WHERE run_id=?", (run_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM runs WHERE parent_id=?", (run_id,)).fetchone()[0], 0)

    def test_seed_all_artifact_categories_reject_modification_and_deletion(self):
        folder = self.data / self.seed
        names = ["original", "image.png", "r003-crop.png", "r003-ocr.png", "r003-ocr.png.tsv", "r003-alt.png", "r003-alt.png.tsv", "source-app.py", "result.json"]
        for name in names:
            path = folder / name
            original = path.read_bytes()
            for operation in ("modify", "remove"):
                with self.subTest(artifact=name, operation=operation):
                    try:
                        if operation == "modify":
                            path.write_bytes(original + b"tampered")
                        else:
                            path.unlink()
                        self.assert_rejected_everywhere(self.seed)
                    finally:
                        path.write_bytes(original)

    def test_new_complete_manifest_rejects_all_retained_artifact_changes(self):
        run_id, folder, result = self.insert_run(self.seed_result)
        result["artifact_manifest"] = build_manifest(folder, result)
        self.save_run(run_id, folder, result)
        code, body = self.request(f"/runs/{run_id}")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["result"]["integrity"]["coverage"], "complete")
        for name in ("r001-ocr.png", "r001-alt.png.tsv", "source-pipeline.py"):
            path = folder / name
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"tampered")
                self.assert_rejected_everywhere(run_id)
            finally:
                path.write_bytes(original)
        path = folder / "r001-ocr.png.tsv"
        original = path.read_bytes()
        try:
            path.unlink()
            self.assert_rejected_everywhere(run_id)
        finally:
            path.write_bytes(original)

    def test_incomplete_or_unexpected_manifest_fails_closed(self):
        for change in ("missing", "extra", "mismatch"):
            with self.subTest(change=change):
                run_id, folder, result = self.insert_run(self.seed_result)
                result["artifact_manifest"] = build_manifest(folder, result)
                files = result["artifact_manifest"]["files"]
                if change == "missing":
                    del files["r001-ocr.png.tsv"]
                elif change == "extra":
                    files["private-notes.txt"] = "0" * 64
                else:
                    files["r001-ocr.png.tsv"] = "0" * 64
                self.save_run(run_id, folder, result)
                self.assert_rejected_everywhere(run_id)

    def test_legacy_coverage_never_trusts_unrecorded_ocr_or_exports_extra_files(self):
        run_id, folder, result = self.insert_run(self.seed_result)
        # This legacy OCR file has no historical checksum. It must not acquire one now.
        (folder / "r001-ocr.png.tsv").write_text("unverifiable legacy bytes", encoding="utf-8")
        (folder / "private-notes.txt").write_text("must never be exported", encoding="utf-8")
        self.save_run(run_id, folder, result)
        raw_before = (folder / "result.json").read_bytes()
        code, body = self.request(f"/runs/{run_id}")
        self.assertEqual(code, 200)
        integrity = json.loads(body)["result"]["integrity"]
        self.assertEqual(integrity["coverage"], "legacy-recorded-hashes")
        self.assertIn("r001-ocr.png.tsv", integrity["unverified_files"])
        code, body = self.request(f"/runs/{run_id}/export?format=bundle")
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertNotIn("r001-ocr.png.tsv", archive.namelist())
            self.assertNotIn("private-notes.txt", archive.namelist())
            self.assertEqual(json.loads(archive.read("integrity.json")), integrity)
            self.assertEqual(archive.read("result.json"), raw_before)
        self.assertEqual((folder / "result.json").read_bytes(), raw_before)

    def test_legacy_completed_digest_adoption_requires_verified_source(self):
        run_id, folder, result = self.insert_run(self.seed_result)
        self.save_run(run_id, folder, result)
        original = (folder / "original").read_bytes()
        (folder / "original").write_bytes(original + b"changed")
        self.assertEqual(self.request(f"/runs/{run_id}")[0], 409)
        with connect(self.data / "graphics.sqlite") as db:
            self.assertIsNone(db.execute("SELECT source_sha256 FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        (folder / "original").write_bytes(original)
        self.assertEqual(self.request(f"/runs/{run_id}")[0], 200)
        with connect(self.data / "graphics.sqlite") as db:
            self.assertEqual(db.execute("SELECT source_sha256 FROM runs WHERE id=?", (run_id,)).fetchone()[0], result["image"]["sha256"])

    def test_untracked_files_and_links_are_not_exported(self):
        folder = self.data / self.seed
        extra = folder / "untracked-private.txt"
        link = folder / "untracked-link"
        try:
            extra.write_text("private content", encoding="utf-8")
            try:
                link.symlink_to(extra)
            except OSError as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            code, body = self.request(f"/runs/{self.seed}/export?format=bundle")
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                self.assertNotIn(extra.name, archive.namelist())
                self.assertNotIn(link.name, archive.namelist())
        finally:
            link.unlink(missing_ok=True)
            extra.unlink(missing_ok=True)

    def test_artifact_symlinks_are_rejected_even_with_matching_bytes(self):
        path = self.data / self.seed / "r003-crop.png"
        backup = Path(self.temporary.name) / "copied-crop.png"
        original = path.read_bytes()
        try:
            backup.write_bytes(original)
            path.unlink()
            try:
                path.symlink_to(backup)
            except OSError as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            self.assert_rejected_everywhere(self.seed)
        finally:
            path.unlink(missing_ok=True)
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
