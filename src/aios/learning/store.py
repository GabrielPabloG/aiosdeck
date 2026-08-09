"""SQLite storage backend for learning governance."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aios.learning.models import (
    CandidateState,
    LearningCandidate,
    ObservationRecord,
)
from aios.storage.threadsafe import ThreadSafeConnection, connect_threadsafe

logger = logging.getLogger("aios.learning.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_execution_id TEXT NOT NULL DEFAULT '',
    source_event TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    suggested_type TEXT NOT NULL DEFAULT 'pattern',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.0,
    risk_level TEXT NOT NULL DEFAULT 'low',
    dedupe_hash TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'draft',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS learning_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER,
    content TEXT NOT NULL,
    suggested_type TEXT NOT NULL DEFAULT 'pattern',
    confidence REAL NOT NULL DEFAULT 0.0,
    risk_level TEXT NOT NULL DEFAULT 'low',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    dedupe_hash TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'draft',
    ingest_version INTEGER NOT NULL DEFAULT 0,
    ingested_memory_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS learning_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    advisor TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    justification TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS learning_materializations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    format TEXT NOT NULL DEFAULT 'md',
    path TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(text: str, default: Any = None) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


class LearningStore:
    def __init__(self, db_path: Path, project_id: str) -> None:
        self._db_path = db_path
        self._project_id = project_id
        self._conn: ThreadSafeConnection | None = None

    def open(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Cannot create directory: {self._db_path.parent}") from exc

        try:
            self._conn = connect_threadsafe(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn = None
            raise RuntimeError(f"Database open failed: {exc}") from exc

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_open(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def insert_observation(self, obs: ObservationRecord) -> int:
        now = _now()
        evidence_json = _json_dumps(obs.evidence_refs)
        cursor = self._execute(
            "INSERT INTO learning_observations "
            "(source_execution_id, source_event, source_id, content, suggested_type, "
            "evidence_refs, confidence, risk_level, dedupe_hash, state, project_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obs.source_execution_id,
                obs.source_event,
                obs.source_id,
                obs.content,
                obs.suggested_type,
                evidence_json,
                obs.confidence,
                obs.risk_level,
                obs.dedupe_hash,
                obs.state or "draft",
                self._project_id,
                now,
            ),
        )
        if self._conn:
            self._conn.commit()
        return cursor.lastrowid if cursor else 0

    def find_observation_by_source(
        self, source_execution_id: str, source_id: str
    ) -> ObservationRecord | None:
        row = self._fetch_one(
            "SELECT id, source_execution_id, source_event, source_id, content, "
            "suggested_type, evidence_refs, confidence, risk_level, dedupe_hash, "
            "state, project_id, created_at "
            "FROM learning_observations "
            "WHERE source_execution_id=? AND source_id=? AND project_id=?",
            (source_execution_id, source_id, self._project_id),
        )
        if row is None:
            return None
        return self._row_to_observation(row)

    def get_observation(self, observation_id: int) -> ObservationRecord | None:
        row = self._fetch_one(
            "SELECT id, source_execution_id, source_event, source_id, content, "
            "suggested_type, evidence_refs, confidence, risk_level, dedupe_hash, "
            "state, project_id, created_at "
            "FROM learning_observations "
            "WHERE id=? AND project_id=?",
            (observation_id, self._project_id),
        )
        if row is None:
            return None
        return self._row_to_observation(row)

    def list_observations_by_state(self, state: str) -> list[ObservationRecord]:
        rows = self._fetch_all(
            "SELECT id, source_execution_id, source_event, source_id, content, "
            "suggested_type, evidence_refs, confidence, risk_level, dedupe_hash, "
            "state, project_id, created_at "
            "FROM learning_observations "
            "WHERE state=? AND project_id=? ORDER BY created_at DESC",
            (state, self._project_id),
        )
        return [self._row_to_observation(row) for row in rows]

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------

    def insert_candidate(self, candidate: LearningCandidate) -> int:
        now = _now()
        evidence_json = _json_dumps(candidate.evidence_refs)
        cursor = self._execute(
            "INSERT INTO learning_candidates "
            "(observation_id, content, suggested_type, confidence, risk_level, "
            "evidence_refs, dedupe_hash, state, ingest_version, ingested_memory_id, "
            "project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidate.observation_id,
                candidate.content,
                candidate.suggested_type,
                candidate.confidence,
                candidate.risk_level,
                evidence_json,
                candidate.dedupe_hash,
                candidate.state or "draft",
                candidate.ingest_version,
                candidate.ingested_memory_id,
                self._project_id,
                now,
                now,
            ),
        )
        if self._conn:
            self._conn.commit()
        return cursor.lastrowid if cursor else 0

    def find_candidate_by_hash(
        self, dedupe_hash: str, states: tuple[str, ...] | None = None
    ) -> LearningCandidate | None:
        if states is None:
            states = ("draft", "scored", "approved", "ingested")
        placeholders = ",".join("?" for _ in states)
        row = self._fetch_one(
            f"SELECT id, observation_id, content, suggested_type, confidence, risk_level, "
            f"evidence_refs, dedupe_hash, state, ingest_version, ingested_memory_id, "
            f"project_id, created_at, updated_at "
            f"FROM learning_candidates "
            f"WHERE dedupe_hash=? AND project_id=? AND state IN ({placeholders}) "
            f"ORDER BY created_at DESC LIMIT 1",
            (dedupe_hash, self._project_id, *states),
        )
        if row is None:
            return None
        return self._row_to_candidate(row)

    def get_candidate(self, candidate_id: int) -> LearningCandidate | None:
        row = self._fetch_one(
            "SELECT id, observation_id, content, suggested_type, confidence, risk_level, "
            "evidence_refs, dedupe_hash, state, ingest_version, ingested_memory_id, "
            "project_id, created_at, updated_at "
            "FROM learning_candidates WHERE id=? AND project_id=?",
            (candidate_id, self._project_id),
        )
        if row is None:
            return None
        return self._row_to_candidate(row)

    def list_candidates(
        self, state: CandidateState | None = None, limit: int = 100
    ) -> list[LearningCandidate]:
        if state:
            rows = self._fetch_all(
                "SELECT id, observation_id, content, suggested_type, confidence, risk_level, "
                "evidence_refs, dedupe_hash, state, ingest_version, ingested_memory_id, "
                "project_id, created_at, updated_at "
                "FROM learning_candidates WHERE project_id=? AND state=? "
                "ORDER BY created_at DESC LIMIT ?",
                (self._project_id, state, limit),
            )
        else:
            rows = self._fetch_all(
                "SELECT id, observation_id, content, suggested_type, confidence, risk_level, "
                "evidence_refs, dedupe_hash, state, ingest_version, ingested_memory_id, "
                "project_id, created_at, updated_at "
                "FROM learning_candidates WHERE project_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (self._project_id, limit),
            )
        return [self._row_to_candidate(row) for row in rows]

    def update_candidate_state(
        self, candidate_id: int, state: CandidateState, **kwargs: Any
    ) -> None:
        now = _now()
        fields = ["state=?", "updated_at=?"]
        params: list[Any] = [state, now]
        for key, value in kwargs.items():
            if key in ("ingest_version", "ingested_memory_id"):
                fields.append(f"{key}=?")
                params.append(value)
        params.append(candidate_id)
        params.append(self._project_id)
        self._execute(
            f"UPDATE learning_candidates SET {', '.join(fields)} WHERE id=? AND project_id=?",
            tuple(params),
        )
        if self._conn:
            self._conn.commit()

    def count_candidates_by_hash(self, dedupe_hash: str) -> int:
        row = self._fetch_one(
            "SELECT COUNT(*) FROM learning_candidates WHERE dedupe_hash=? AND project_id=?",
            (dedupe_hash, self._project_id),
        )
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def insert_review(  # noqa: PLR0913, PLR0917
        self,
        candidate_id: int,
        advisor: str,
        recommendation: str,
        justification: str,
        reviewer: str,
        decision: str,
        reason: str,
    ) -> int:
        now = _now()
        cursor = self._execute(
            "INSERT INTO learning_reviews "
            "(candidate_id, advisor, recommendation, justification, reviewer, decision, reason, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (candidate_id, advisor, recommendation, justification, reviewer, decision, reason, now),
        )
        if self._conn:
            self._conn.commit()
        return cursor.lastrowid if cursor else 0

    def get_reviews(self, candidate_id: int) -> list[dict]:
        rows = self._fetch_all(
            "SELECT id, candidate_id, advisor, recommendation, justification, "
            "reviewer, decision, reason, created_at "
            "FROM learning_reviews WHERE candidate_id=? ORDER BY created_at",
            (candidate_id,),
        )
        return [
            {
                "id": r[0],
                "candidate_id": r[1],
                "advisor": r[2],
                "recommendation": r[3],
                "justification": r[4],
                "reviewer": r[5],
                "decision": r[6],
                "reason": r[7],
                "created_at": r[8],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Materializations
    # ------------------------------------------------------------------

    def insert_materialization(self, fmt: str, path: str, count: int) -> int:
        now = _now()
        cursor = self._execute(
            "INSERT INTO learning_materializations (format, path, candidate_count, created_at) "
            "VALUES (?, ?, ?, ?)",
            (fmt, path, count, now),
        )
        if self._conn:
            self._conn.commit()
        return cursor.lastrowid if cursor else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor | None:
        if self._conn:
            return self._conn.execute(query, params)
        return None

    def _fetch_one(self, query: str, params: tuple = ()) -> tuple | None:
        if not self._conn:
            return None
        try:
            return self._conn.execute(query, params).fetchone()
        except sqlite3.Error as exc:
            logger.error("Query error: %s", exc)
            return None

    def _fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        if not self._conn:
            return []
        try:
            return self._conn.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            logger.error("Query error: %s", exc)
            return []

    @staticmethod
    def _row_to_observation(row: tuple) -> ObservationRecord:
        return ObservationRecord(
            id=row[0],
            source_execution_id=row[1],
            source_event=row[2],
            source_id=row[3],
            content=row[4],
            suggested_type=row[5],
            evidence_refs=_json_loads(row[6], []),
            confidence=row[7],
            risk_level=row[8],
            dedupe_hash=row[9],
            state=row[10],  # type: ignore[arg-type]
            project_id=row[11],
            created_at=row[12],
        )

    @staticmethod
    def _row_to_candidate(row: tuple) -> LearningCandidate:
        return LearningCandidate(
            id=row[0],
            observation_id=row[1],
            content=row[2],
            suggested_type=row[3] if row[3] else "pattern",
            confidence=row[4],
            risk_level=row[5],
            evidence_refs=_json_loads(row[6], []),
            dedupe_hash=row[7],
            state=row[8],  # type: ignore[arg-type]
            ingest_version=row[9],
            ingested_memory_id=row[10],
            project_id=row[11],
            created_at=row[12],
            updated_at=row[13],
        )
