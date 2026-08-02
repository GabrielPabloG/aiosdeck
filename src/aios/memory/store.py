"""SQLite storage backend. Implementation detail of MemoryEngine."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from aios.memory.models import Convention, Decision, Mistake, Pattern

logger = logging.getLogger("aios.memory.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT '',
    rule TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL,
    consequences TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    usage_count INTEGER NOT NULL DEFAULT 0,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'warning',
    project_id TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
"""


class SQLiteStore:
    def __init__(self, db_path: Path, project_id: str) -> None:
        self._db_path = db_path
        self._project_id = project_id
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_open(self) -> bool:
        return self._conn is not None

    def get_conventions(self) -> list[Convention]:
        rows = self._fetch_all(
            "SELECT id, category, rule, source, project_id, created_at, last_seen "
            "FROM conventions WHERE project_id=? ORDER BY last_seen DESC",
            (self._project_id,),
        )
        return [Convention(*row) for row in rows]

    def get_decisions(self, status: str = "active") -> list[Decision]:
        rows = self._fetch_all(
            "SELECT id, title, context, decision, consequences, status, project_id, created_at "
            "FROM decisions WHERE project_id=? AND status=? ORDER BY created_at DESC",
            (self._project_id, status),
        )
        return [Decision(*row) for row in rows]

    def get_patterns(self) -> list[Pattern]:
        rows = self._fetch_all(
            "SELECT id, name, description, usage_count, project_id, created_at "
            "FROM patterns WHERE project_id=? ORDER BY usage_count DESC",
            (self._project_id,),
        )
        return [Pattern(*row) for row in rows]

    def get_mistakes(self, resolved: bool = False) -> list[Mistake]:
        if resolved:
            clause = "project_id=? AND resolved_at IS NOT NULL"
        else:
            clause = "project_id=? AND resolved_at IS NULL"
        rows = self._fetch_all(
            f"SELECT id, description, category, severity, project_id, resolved_at, created_at "
            f"FROM mistakes WHERE {clause} ORDER BY created_at DESC",
            (self._project_id,),
        )
        return [Mistake(*row) for row in rows]

    def upsert_convention(self, rule: str, category: str, source: str) -> None:
        now = _now()
        existing = self._fetch_one(
            "SELECT id FROM conventions WHERE rule=? AND project_id=?",
            (rule, self._project_id),
        )
        if existing:
            self._execute(
                "UPDATE conventions SET last_seen=?, category=?, source=? WHERE id=?",
                (now, category, source, existing[0]),
            )
        else:
            self._execute(
                "INSERT INTO conventions "
                "(rule, category, source, project_id, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rule, category, source, self._project_id, now, now),
            )
        self._conn.commit()

    def add_decision(self, title: str, context: str, decision: str, consequences: str) -> None:
        now = _now()
        self._execute(
            "INSERT INTO decisions "
            "(title, context, decision, consequences, status, project_id, created_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (title, context, decision, consequences, self._project_id, now),
        )
        self._conn.commit()

    def add_pattern(self, name: str, description: str) -> None:
        now = _now()
        existing = self._fetch_one(
            "SELECT id, usage_count FROM patterns WHERE name=? AND project_id=?",
            (name, self._project_id),
        )
        if existing:
            self._execute(
                "UPDATE patterns SET usage_count=usage_count+1 WHERE id=?",
                (existing[0],),
            )
        else:
            self._execute(
                "INSERT INTO patterns (name, description, usage_count, project_id, created_at) "
                "VALUES (?, ?, 1, ?, ?)",
                (name, description, self._project_id, now),
            )
        self._conn.commit()

    def add_mistake(self, description: str, category: str, severity: str) -> None:
        now = _now()
        self._execute(
            "INSERT INTO mistakes (description, category, severity, project_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (description, category, severity, self._project_id, now),
        )
        self._conn.commit()

    def _fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        if not self._conn:
            return []
        try:
            return self._conn.execute(query, params).fetchall()
        except sqlite3.Error:
            return []

    def _fetch_one(self, query: str, params: tuple = ()) -> tuple | None:
        if not self._conn:
            return None
        try:
            return self._conn.execute(query, params).fetchone()
        except sqlite3.Error:
            return None

    def _execute(self, query: str, params: tuple = ()) -> None:
        if self._conn:
            self._conn.execute(query, params)


def _now() -> str:
    return datetime.now(UTC).isoformat()
