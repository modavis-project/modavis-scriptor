#!/usr/bin/env python3
"""Disposable real-crash, concurrency, memory, backup, and restore regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import patch

from backups import create_backup, restore_backup, verify_backup
import backups
from database import SCHEMA_VERSION, connect, migrate
from delivery import TemporaryFileResponse
from evidence import IntegrityError, build_manifest, sha256, verified_copy
from jobs import recover
from storage import admission_folder, clear_abandoned_admissions, publish_exclusive, service_owner

SERVICE = Path(importlib.util.find_spec("app").origin).parent


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="scriptor-reliability-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.workspace = Path(cls.temporary.name)
        cls.data = cls.workspace / "data"
        cls.processes = []
        cls.addClassCleanup(cls.stop_all)
        cls.start()
        cls.seed = "example-organ-stops-v1"

    @classmethod
    def start(cls):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        log = (cls.workspace / f"service-{len(cls.processes)}.log").open("wb")
        cls.addClassCleanup(log.close)
        env = {**os.environ, "GRAPHICS_DATA": str(cls.data), "SCRIPTOR_DISPOSABLE_TEST": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        cls.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)], cwd=SERVICE, env=env, stdout=log, stderr=subprocess.STDOUT)
        cls.processes.append(cls.process)
        for _ in range(400):
            if cls.process.poll() is not None:
                raise RuntimeError((cls.workspace / f"service-{len(cls.processes)-1}.log").read_text(encoding="utf-8"))
            try:
                status, body = cls.request("/health")
                if status == 200 and json.loads(body)["disposable_test_instance"]:
                    return
            except OSError:
                pass
            time.sleep(.05)
        raise RuntimeError("Disposable API did not become ready")

    @classmethod
    def stop_all(cls):
        for process in cls.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        process.kill()
                    process.wait(timeout=10)

    @classmethod
    def request(cls, path, method="GET", payload=None):
        request = urllib.request.Request(cls.base + path, data=json.dumps(payload).encode() if payload is not None else None, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def completed(self, run_id, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, body = self.request(f"/runs/{run_id}")
            self.assertEqual(status, 200, body[:300])
            data = json.loads(body)
            if data["run"]["status"] == "completed":
                return data
            self.assertNotEqual(data["run"]["status"], "failed", data)
            time.sleep(.1)
        self.fail("Actual OCR did not complete within timeout")

    def test_01_killed_real_ocr_restarts_without_source_or_review_loss(self):
        self.assertIsNotNone(shutil.which("tesseract"), "Real crash regression requires Tesseract")
        status, body = self.request(f"/runs/{self.seed}/rerun", "POST", {"mode": "graphics", "regions": [[0, 0, 1, 1]]})
        self.assertEqual(status, 202, body)
        run_id = json.loads(body)["id"]
        source_digest = sha256(self.data / run_id / "original")
        marker = None
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            markers = list((self.data / run_id).glob(".attempt-*/.ocr-active.json"))
            if markers:
                try:
                    marker = json.loads(markers[0].read_text(encoding="utf-8"))
                    old_stage = markers[0].parent
                    break
                except (OSError, ValueError):
                    pass
            time.sleep(.01)
        self.assertIsNotNone(marker, "No active real Tesseract invocation observed")
        self.assertEqual(marker["parent_pid"], self.process.pid)
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(self.process.pid, signal.SIGKILL)
            # This PID was recorded by this private service, during this exact attempt.
            try:
                os.kill(marker["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process.wait(timeout=10)
        self.assertEqual(sha256(self.data / run_id / "original"), source_digest)
        self.assertFalse((self.data / run_id / "processed/result.json").exists())
        self.__class__.start()
        data = self.completed(run_id)
        self.assertEqual(data["result"]["image"]["sha256"], source_digest)
        self.assertEqual(data["run"]["source_sha256"], source_digest)
        self.assertEqual(data["result"]["integrity"]["coverage"], "complete")
        self.assertEqual(data["result"]["review_events"], [])
        self.assertFalse(old_stage.exists())
        self.assertEqual(data["run"]["artifact_path"], "processed")

    def test_02_concurrent_reviews_record_each_success_exactly_once(self):
        path = f"/runs/{self.seed}/regions/r003/review"
        baseline = json.loads(self.request(f"/runs/{self.seed}")[1])["result"]
        barrier = threading.Barrier(8)
        def initial(index):
            barrier.wait(timeout=10)
            return self.request(path, "PATCH", {"action": "retain", "reviewer": f"Concurrent {index}", "rationale": "Visible source evidence retained", "expected_version": 0})[0]
        with ThreadPoolExecutor(max_workers=8) as workers:
            statuses = list(workers.map(initial, range(8)))
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(409), 7)
        def repeated(index):
            successes = 0
            for decision in range(4):
                for _ in range(100):
                    current = json.loads(self.request(f"/runs/{self.seed}")[1])["result"]
                    version = current["regions"][2]["version"]
                    status, body = self.request(path, "PATCH", {"action": "retain", "reviewer": f"Reviewer {index}", "rationale": f"Visible evidence decision {index}/{decision}", "expected_version": version})
                    if status == 200:
                        successes += 1
                        break
                    self.assertEqual(status, 409, body[:200])
                else:
                    self.fail("Review stress retry limit exceeded")
            return successes
        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(sum(workers.map(repeated, range(4))), 16)
        result = json.loads(self.request(f"/runs/{self.seed}")[1])["result"]
        self.assertEqual([event["version"] for event in result["review_events"]], list(range(1, 18)))
        self.assertEqual(result["regions"][2]["raw_text"], baseline["regions"][2]["raw_text"])
        self.assertEqual(result["immutable_result_sha256"], baseline["immutable_result_sha256"])

    def test_03_live_backup_restore_rehearsal_and_nonoverwrite(self):
        archive = self.workspace / "verified-backup.zip"
        real_collect = backups.managed_files
        pending = []
        def review_while_snapshot_locked(data):
            if Path(data).resolve() == self.data.resolve() and not pending:
                pending.append(workers.submit(self.request, f"/runs/{self.seed}/regions/r003/review", "PATCH", {"action": "retain", "reviewer": "During backup", "rationale": "Concurrent visible evidence review", "expected_version": 17}))
                time.sleep(.1)
                self.assertFalse(pending[0].done(), "Review write must wait for consistent backup snapshot")
            return real_collect(data)
        with ThreadPoolExecutor(max_workers=1) as workers, patch.object(backups, "managed_files", side_effect=review_while_snapshot_locked):
            manifest = create_backup(self.data, archive)
            self.assertEqual(pending[0].result(timeout=20)[0], 200)
        self.assertEqual(manifest["store_report"]["review_events"], 17)
        self.assertEqual(verify_backup(archive)["store_report"], manifest["store_report"])
        cli = subprocess.run([sys.executable, "-m", "backups", "verify", str(archive)], cwd=SERVICE, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["status"], "verified")
        restored = self.workspace / "restored"
        restore_backup(archive, restored)
        self.assertEqual(sha256(restored / "graphics.sqlite"), manifest["files"]["graphics.sqlite"]["sha256"])
        with connect(restored / "graphics.sqlite") as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(db.execute("SELECT count(*) FROM review_events").fetchone()[0], 17)
        archive_digest = sha256(archive)
        with self.assertRaises(FileExistsError):
            create_backup(self.data, archive)
        with self.assertRaises(FileExistsError):
            restore_backup(archive, restored)
        self.assertEqual(sha256(archive), archive_digest)

    def test_04_corrupt_archive_and_unsafe_paths_never_publish_restore(self):
        source = self.workspace / "verified-backup.zip"
        corrupted = self.workspace / "corrupt-backup.zip"
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(corrupted, "w") as destination:
            for name in original.namelist():
                content = original.read(name)
                if name.endswith("/original"):
                    content += b"corrupted"
                destination.writestr(name, content)
        target = self.workspace / "should-not-exist"
        with self.assertRaises((IntegrityError, zipfile.BadZipFile)):
            restore_backup(corrupted, target)
        self.assertFalse(target.exists())
        hostile = self.workspace / "hostile.zip"
        with zipfile.ZipFile(hostile, "w") as archive:
            archive.writestr("../escaped", b"bad")
            archive.writestr("backup.json", json.dumps({"schema": "modavis-scriptor.backup/v1", "files": {"../escaped": {"sha256": hashlib.sha256(b"bad").hexdigest(), "size": 3}}}))
        with self.assertRaises(IntegrityError):
            restore_backup(hostile, target)
        self.assertFalse((self.workspace / "escaped").exists())
        self.assertFalse(target.exists())

    def test_05_corrupt_source_refuses_backup_without_publishing_archive(self):
        source = self.data / self.seed / "r003-crop.png"
        original = source.read_bytes()
        target = self.workspace / "refused.zip"
        try:
            source.write_bytes(original + b"corrupt")
            with self.assertRaises(IntegrityError):
                create_backup(self.data, target)
            self.assertFalse(target.exists())
        finally:
            source.write_bytes(original)


class StoreUnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="scriptor-store-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "data"
        self.data.mkdir()
        with patch.dict(os.environ, {"GRAPHICS_DATA": str(self.data)}):
            self.api = importlib.import_module("app")
        self.api.DATA = self.data
        with self.api.connection() as db:
            migrate(db)

    def test_queue_stress_keeps_exact_capacity_and_no_abandoned_reservations(self):
        barrier = threading.Barrier(24)
        def admission(_):
            run_id = uuid.uuid4().hex
            folder = admission_folder(self.data, run_id)
            (folder / "original").write_bytes(b"source")
            barrier.wait(timeout=15)
            try:
                self.api.admit_run(run_id, folder, "Stress", "Disposable", "{}", self.api.Config().model_dump_json(), hashlib.sha256(b"source").hexdigest())
                return 202
            except self.api.HTTPException as error:
                self.assertFalse(folder.exists())
                return error.status_code
        with ThreadPoolExecutor(max_workers=24) as workers:
            results = list(workers.map(admission, range(24)))
        self.assertEqual(results.count(202), 10)
        self.assertEqual(results.count(429), 14)
        orphan_id = uuid.uuid4().hex
        orphan = admission_folder(self.data, orphan_id)
        (orphan / "original").write_bytes(b"orphan before DB commit")
        with self.api.connection() as db:
            known = {r[0] for r in db.execute("SELECT id FROM runs")}
        clear_abandoned_admissions(self.data, known)
        self.assertFalse(orphan.exists())
        self.assertEqual({p.name for p in self.data.iterdir() if p.is_dir()}, known)

    def test_prepared_publication_finishes_after_restart_without_running_ocr(self):
        run_id, attempt = uuid.uuid4().hex, uuid.uuid4().hex
        folder = self.data / run_id
        folder.mkdir()
        shutil.copyfile(SERVICE / "example/processed/original", folder / "original")
        stage = folder / (".attempt-" + attempt)
        shutil.copytree(SERVICE / "example/processed", stage)
        result = json.loads((stage / "result.json").read_text(encoding="utf-8"))
        result["run_id"] = run_id
        result["artifact_manifest"] = build_manifest(stage, result)
        (stage / "result.json").write_text(json.dumps(result), encoding="utf-8")
        with self.api.connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,result_sha256,source_sha256,artifact_path,attempt_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (run_id, "Prepared", "Disposable", "running", "date", json.dumps(result["metadata"]), json.dumps(result["paradata"]["config"]), sha256(stage / "result.json"), result["image"]["sha256"], "processed", attempt))
        self.assertEqual(recover(self.data, self.api.connection, SERVICE), [])
        row = self.api.run_record(run_id)
        self.assertEqual(row["status"], "completed")
        self.assertIsNone(row["attempt_id"])
        self.assertFalse(stage.exists())
        self.assertTrue((folder / "processed/result.json").exists())
        self.assertEqual(self.api.result_for(run_id)["integrity"]["coverage"], "complete")

    def test_verified_copy_memory_does_not_scale_with_artifact_size(self):
        folder = self.data / "large"
        folder.mkdir()
        path = folder / "r001-ocr.png.tsv"
        block = b"bounded artifact transport\n" * 16384
        checksum = hashlib.sha256()
        with path.open("wb") as stream:
            for _ in range(160):
                stream.write(block)
                checksum.update(block)
        destination = Path(self.temporary.name) / "spool"
        tracemalloc.start()
        try:
            with destination.open("wb") as stream:
                size = verified_copy(folder, path.name, checksum.hexdigest(), stream)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertGreater(size, 64 * 1024 * 1024)
        self.assertLess(peak, 3 * 1024 * 1024, f"Peak Python allocation was {peak}")
        self.assertEqual(sha256(destination), checksum.hexdigest())

    def test_response_spool_is_removed_after_disconnect(self):
        path = Path(self.temporary.name) / "response-spool"
        path.write_bytes(b"body" * 100000)
        response = TemporaryFileResponse(path)
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("simulated disconnected client")
        with self.assertRaises(OSError):
            asyncio.run(response({"type": "http", "method": "GET", "headers": [], "extensions": {}}, receive, send))
        self.assertFalse(path.exists())

    def test_restore_syncs_nested_directory_entries_before_publication(self):
        run_id = uuid.uuid4().hex
        folder = self.data / run_id
        folder.mkdir()
        (folder / "original").write_bytes(b"preserved failed source")
        with self.api.connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,source_sha256) VALUES(?,?,?,?,?,?,?,?)", (run_id, "Durability", "Disposable", "failed", "date", "{}", self.api.Config().model_dump_json(), sha256(folder / "original")))
        archive = Path(self.temporary.name) / "durable.zip"
        create_backup(self.data, archive)
        target = Path(self.temporary.name) / "durable-restored"
        synced = []
        real_sync, real_publish = backups.sync_directory, backups.publish_exclusive
        def sync(path):
            synced.append(Path(path))
            return real_sync(path)
        def publish(stage, destination):
            directories = [stage, *(path for path in stage.rglob("*") if path.is_dir())]
            self.assertGreater(len(directories), 1)
            self.assertTrue(set(directories).issubset(set(synced)))
            for directory in directories:
                if directory != stage:
                    self.assertLess(synced.index(directory), synced.index(directory.parent))
            return real_publish(stage, destination)
        with patch.object(backups, "sync_directory", side_effect=sync), patch.object(backups, "publish_exclusive", side_effect=publish):
            restore_backup(archive, target)
        self.assertEqual((target / run_id / "original").read_bytes(), b"preserved failed source")

    def test_backup_refuses_unrecognized_schema_without_creating_archive(self):
        with self.api.connection() as db:
            db.execute("ALTER TABLE runs ADD COLUMN unknown_schema_column TEXT")
        archive = Path(self.temporary.name) / "invalid-schema.zip"
        with self.assertRaisesRegex(RuntimeError, "Unrecognized"):
            create_backup(self.data, archive)
        self.assertFalse(archive.exists())

    def test_duplicate_service_owner_is_refused(self):
        with service_owner(self.data):
            with self.assertRaisesRegex(RuntimeError, "already owns"):
                with service_owner(self.data):
                    self.fail("Duplicate owner was admitted")

    def test_worker_start_failure_releases_queue_reservation_without_deleting_source(self):
        run_id = uuid.uuid4().hex
        folder = admission_folder(self.data, run_id)
        (folder / "original").write_bytes(b"preserve on scheduling failure")
        digest = sha256(folder / "original")
        self.api.admit_run(run_id, folder, "Failure", "Disposable", "{}", self.api.Config().model_dump_json(), digest)
        with patch.object(self.api.POOL, "submit", side_effect=RuntimeError("stopped executor")):
            with self.assertRaises(self.api.HTTPException) as error:
                self.api.schedule(run_id)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.api.run_record(run_id)["status"], "failed")
        self.assertEqual(sha256(folder / "original"), digest)
        with self.api.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0], 0)

    def test_legacy_backup_preserves_unverified_ocr_without_creating_historical_hashes(self):
        run_id = uuid.uuid4().hex
        folder = self.data / run_id
        shutil.copytree(SERVICE / "example/processed", folder)
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        result["run_id"] = run_id
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        raw_result = (folder / "result.json").read_bytes()
        text = "Ungeprüfte historische OCR — Scharff äöü\n".encode("utf-8")
        (folder / "r001-ocr.png.tsv").write_bytes(text)
        with self.api.connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,result_sha256) VALUES(?,?,?,?,?,?,?,?)", (run_id, "Legacy", "Disposable", "completed", "date", json.dumps(result["metadata"]), json.dumps(result["paradata"]["config"]), sha256(folder / "result.json")))
        archive = Path(self.temporary.name) / "legacy.zip"
        manifest = create_backup(self.data, archive)
        self.assertIn(f"{run_id}/r001-ocr.png.tsv", manifest["store_report"]["historically_unverified_files"])
        restored = Path(self.temporary.name) / "legacy-restored"
        restore_backup(archive, restored)
        self.assertEqual((restored / run_id / "result.json").read_bytes(), raw_result)
        self.assertEqual((restored / run_id / "r001-ocr.png.tsv").read_bytes(), text)
        self.assertNotIn("artifact_manifest", json.loads(raw_result))
        with connect(restored / "graphics.sqlite") as db:
            self.assertIsNone(db.execute("SELECT source_sha256 FROM runs WHERE id=?", (run_id,)).fetchone()[0])

    def test_research_zip_uses_bounded_memory_and_cleans_failed_response(self):
        run_id = uuid.uuid4().hex
        folder = self.data / run_id
        shutil.copytree(SERVICE / "example/processed", folder)
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        result["run_id"] = run_id
        block = b"large retained OCR TSV\n" * 32768
        with (folder / "r001-ocr.png.tsv").open("ab") as stream:
            for _ in range(100):
                stream.write(block)
        result["artifact_manifest"] = build_manifest(folder, result)
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        with self.api.connection() as db:
            db.execute("INSERT INTO runs(id,title,project,status,created_at,metadata,config,result_sha256,source_sha256) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, "Large", "Disposable", "completed", "date", json.dumps(result["metadata"]), json.dumps(result["paradata"]["config"]), sha256(folder / "result.json"), result["image"]["sha256"]))
        tracemalloc.start()
        try:
            response = self.api.export(run_id, "bundle")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 12 * 1024 * 1024, f"ZIP peak Python allocation was {peak}")
        path = Path(response.path)
        self.assertTrue(path.exists())
        with zipfile.ZipFile(path) as archive:
            self.assertGreater(archive.getinfo("r001-ocr.png.tsv").file_size, 64 * 1024 * 1024)
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("disconnected")
        with self.assertRaises(OSError):
            asyncio.run(response({"type": "http", "method": "GET", "headers": [], "extensions": {}}, receive, send))
        self.assertFalse(path.exists())

    def test_nonoverwrite_publication_never_changes_existing_target(self):
        source, target = self.data / "source", self.data / "target"
        source.mkdir()
        target.mkdir()
        (target / "preserve").write_text("existing data", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            publish_exclusive(source, target)
        self.assertEqual((target / "preserve").read_text(encoding="utf-8"), "existing data")
        self.assertTrue(source.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
