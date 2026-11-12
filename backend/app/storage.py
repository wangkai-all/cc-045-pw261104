"""SQLite persistence. One connection per request, foreign keys on."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .config import DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_id INTEGER NOT NULL REFERENCES schemas(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    fields_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','locked')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (schema_id, version)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES schema_versions(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    total_lines INTEGER NOT NULL,
    problem_count INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_version_id INTEGER NOT NULL REFERENCES schema_versions(id),
    target_version_id INTEGER NOT NULL REFERENCES schema_versions(id),
    rules_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    artifact_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','generated')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA_SQL)


# ---- schema / version helpers -------------------------------------------------

def create_schema(conn: sqlite3.Connection, name: str, description: str) -> int:
    cur = conn.execute(
        "INSERT INTO schemas (name, description) VALUES (?, ?)",
        (name, description),
    )
    return int(cur.lastrowid)


def list_schemas(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM schema_versions v WHERE v.schema_id=s.id) AS version_count
           FROM schemas s ORDER BY s.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_schema(conn: sqlite3.Connection, schema_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM schemas WHERE id=?", (schema_id,)).fetchone()
    return dict(row) if row else None


def create_version(conn: sqlite3.Connection, schema_id: int, version: str,
                   note: str, fields: list[dict]) -> int:
    cur = conn.execute(
        """INSERT INTO schema_versions (schema_id, version, note, fields_json, status)
           VALUES (?, ?, ?, ?, 'draft')""",
        (schema_id, version, note, json.dumps(fields, ensure_ascii=False)),
    )
    return int(cur.lastrowid)


def update_draft_fields(conn: sqlite3.Connection, version_id: int,
                        fields: list[dict], note: Optional[str] = None) -> None:
    version = get_version(conn, version_id)
    if version is None:
        raise KeyError(f"版本 {version_id} 不存在")
    if version["status"] == "locked":
        raise PermissionError("结构版本已锁定，不能修改字段结构")
    if note is not None:
        conn.execute("UPDATE schema_versions SET fields_json=?, note=? WHERE id=?",
                     (json.dumps(fields, ensure_ascii=False), note, version_id))
    else:
        conn.execute("UPDATE schema_versions SET fields_json=? WHERE id=?",
                     (json.dumps(fields, ensure_ascii=False), version_id))


def lock_version(conn: sqlite3.Connection, version_id: int) -> None:
    version = get_version(conn, version_id)
    if version is None:
        raise KeyError(f"版本 {version_id} 不存在")
    if version["status"] == "locked":
        return
    conn.execute("UPDATE schema_versions SET status='locked' WHERE id=?", (version_id,))


def get_version(conn: sqlite3.Connection, version_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM schema_versions WHERE id=?", (version_id,)
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["fields"] = json.loads(out.pop("fields_json"))
    return out


def list_versions(conn: sqlite3.Connection, schema_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, schema_id, version, note, status, created_at
           FROM schema_versions WHERE schema_id=? ORDER BY id""",
        (schema_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def save_upload(conn: sqlite3.Connection, version_id: int, filename: str,
                report: dict, source_path: str) -> int:
    cur = conn.execute(
        """INSERT INTO uploads (version_id, filename, source_path, total_lines,
                                problem_count, passed, report_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (version_id, filename, source_path, report["total_lines"],
         report["problem_count"], 1 if report["passed"] else 0,
         json.dumps(report, ensure_ascii=False)),
    )
    return int(cur.lastrowid)


def list_uploads(conn: sqlite3.Connection, version_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, filename, total_lines, problem_count, passed, created_at "
        "FROM uploads WHERE version_id=? ORDER BY id DESC",
        (version_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_upload(conn: sqlite3.Connection, upload_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["report"] = json.loads(out.pop("report_json"))
    return out


def save_mapping(conn: sqlite3.Connection, source_id: int, target_id: int,
                 rules: list[dict], preview: dict, artifact_path: Optional[str]) -> int:
    status = "generated" if artifact_path else "draft"
    cur = conn.execute(
        """INSERT INTO mappings (source_version_id, target_version_id, rules_json,
                                 preview_json, artifact_path, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (source_id, target_id, json.dumps(rules, ensure_ascii=False),
         json.dumps(preview, ensure_ascii=False), artifact_path, status),
    )
    return int(cur.lastrowid)


def get_mapping(conn: sqlite3.Connection, mapping_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM mappings WHERE id=?", (mapping_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["rules"] = json.loads(out.pop("rules_json"))
    out["preview"] = json.loads(out.pop("preview_json"))
    return out
