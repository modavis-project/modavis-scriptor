"""Transactional, versioned SQLite initialization; never downgrade a newer database."""
from contextlib import contextmanager
from datetime import datetime, timezone
import re
import sqlite3

SCHEMA_VERSION = 2
TABLE_COLUMNS = {
    "runs": {"id", "title", "project", "status", "created_at", "metadata", "config", "parent_id", "error", "result_sha256"},
    "review_events": {"id", "run_id", "region_id", "version", "payload", "created_at"},
}
TRIGGERS = {
    "review_no_update": "CREATE TRIGGER review_no_update BEFORE UPDATE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END",
    "review_no_delete": "CREATE TRIGGER review_no_delete BEFORE DELETE ON review_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END",
}
BASELINE = [
    "CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,metadata TEXT NOT NULL,config TEXT NOT NULL,parent_id TEXT,error TEXT,result_sha256 TEXT)",
    "CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),region_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,region_id,version))",
    "CREATE INDEX IF NOT EXISTS review_lookup ON review_events(run_id,region_id,version)",
    *TRIGGERS.values(),
    "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)",
]


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def normalized_sql(sql):
    return re.sub(r"\s+", "", sql or "").rstrip(";").casefold()


def validate_legacy(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if not tables:
        return
    if tables != set(TABLE_COLUMNS):
        raise RuntimeError("Unrecognized unversioned database; migration refused without changing data")
    for table, expected in TABLE_COLUMNS.items():
        columns = list(db.execute(f"PRAGMA table_info({table})"))
        if {r[1] for r in columns} != expected:
            raise RuntimeError(f"Unrecognized legacy {table} schema; migration refused")
        for _, name, kind, not_null, default, primary_key in columns:
            expected_type = "INTEGER" if table == "review_events" and name in {"id", "version"} else "TEXT"
            nullable = name == "id" or (table == "runs" and name in {"parent_id", "error", "result_sha256"})
            if (kind.upper(), not_null, default, primary_key) != (expected_type, int(not nullable), None, int(name == "id")):
                raise RuntimeError(f"Unrecognized legacy {table}.{name} definition; migration refused")
    indexes = list(db.execute("PRAGMA index_list(review_events)"))
    if not any(r[2] and [c[2] for c in db.execute(f'PRAGMA index_info("{r[1]}")')] == ["run_id", "region_id", "version"] for r in indexes):
        raise RuntimeError("Legacy review version uniqueness is missing; migration refused")
    foreign_keys = list(db.execute("PRAGMA foreign_key_list(review_events)"))
    if not any(r[2:5] == ("runs", "run_id", "id") for r in foreign_keys):
        raise RuntimeError("Legacy review foreign key is missing; migration refused")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("Legacy database has invalid references; migration refused")
    for name, sql in TRIGGERS.items():
        existing = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)).fetchone()
        if existing and normalized_sql(existing[0]) != normalized_sql(sql):
            raise RuntimeError(f"Unrecognized {name} trigger; migration refused")


def validate_ledger(db, version):
    if version == 0:
        return
    try:
        ledger = [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
    except sqlite3.DatabaseError as error:
        raise RuntimeError("Database migration ledger is missing or invalid") from error
    if ledger != list(range(1, version + 1)):
        raise RuntimeError("Database migration ledger does not match its schema version")


def migrate(db):
    """Adopt the known 0.1 schema or upgrade atomically; preserve every review row."""
    # Version and ledger must be read under the same lock. A pre-lock ledger check
    # can reject a valid database if another starter commits its migration between reads.
    db.execute("BEGIN IMMEDIATE")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema {version} is newer than supported {SCHEMA_VERSION}; use newer software")
        validate_ledger(db, version)
        for target in range(version + 1, SCHEMA_VERSION + 1):
            if target == 1:
                validate_legacy(db)
                for statement in BASELINE:
                    if statement.startswith("CREATE TRIGGER"):
                        statement = statement.replace("CREATE TRIGGER", "CREATE TRIGGER IF NOT EXISTS", 1)
                    db.execute(statement)
            elif target == 2:
                # Old runs stay NULL until their preserved result/evidence validates the source.
                db.execute("ALTER TABLE runs ADD COLUMN source_sha256 TEXT")
            db.execute("INSERT INTO schema_migrations VALUES(?,?)", (target, datetime.now(timezone.utc).isoformat()))
            db.execute(f"PRAGMA user_version={target}")
        db.commit()
    except Exception:
        db.rollback()
        raise
