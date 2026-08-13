"""SQLite storage backend for Knowledge Store.

Coexists with memory and telemetry tables in .aios/memory.db.
Uses knowledge_* namespace for all tables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from aios.knowledge.chunking import chunk_text
from aios.knowledge.chunking import content_hash as compute_hash
from aios.knowledge.models import (
    VALID_SOURCE_TYPES,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSource,
)
from aios.storage.sqlite import BaseSQLiteStore
from aios.storage.threadsafe import ThreadSafeConnection

logger = logging.getLogger("aios.knowledge.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    hash TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    indexed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    project_id TEXT NOT NULL,
    UNIQUE(source_id, project_id)
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    hash TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    indexed_at TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    UNIQUE(document_id, project_id)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    document_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    position INTEGER NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    project_id TEXT NOT NULL,
    UNIQUE(chunk_id, project_id)
);

CREATE TABLE IF NOT EXISTS knowledge_index_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    sources_scanned INTEGER NOT NULL DEFAULT 0,
    sources_skipped INTEGER NOT NULL DEFAULT 0,
    sources_reindexed INTEGER NOT NULL DEFAULT 0,
    chunks_created INTEGER NOT NULL DEFAULT 0,
    chunks_deleted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    project_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ks_source ON knowledge_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_ks_project ON knowledge_sources(project_id);
CREATE INDEX IF NOT EXISTS idx_kd_source ON knowledge_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_kd_project ON knowledge_documents(project_id);
CREATE INDEX IF NOT EXISTS idx_kc_source ON knowledge_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_kc_document ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_kc_project ON knowledge_chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_kir_project ON knowledge_index_runs(project_id);

CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    vector_dim INTEGER NOT NULL DEFAULT 0,
    vector_blob TEXT NOT NULL DEFAULT '[]',
    embedding_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    UNIQUE(chunk_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_ke_chunk ON knowledge_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_ke_project ON knowledge_embeddings(project_id);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    chunk_id UNINDEXED,
    source_id UNINDEXED,
    document_id UNINDEXED,
    content,
    project_id UNINDEXED
);
"""


def deterministic_source_id(source_type: str, path: str) -> str:
    return hashlib.sha256(f"{source_type}|{path}".encode()).hexdigest()


class SQLiteKnowledgeStore(BaseSQLiteStore):
    def __init__(
        self,
        db_path: Path,
        project_id: str,
        *,
        connection: ThreadSafeConnection | None = None,
    ) -> None:
        super().__init__(
            db_path, project_id, SCHEMA, error_class=KnowledgeError, connection=connection
        )
        self._fts_available = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _post_open(self) -> None:
        """Create FTS5 virtual table if available (best-effort)."""
        try:
            self._conn.execute(FTS_SCHEMA)
            self._fts_available = True
        except sqlite3.OperationalError:
            self._fts_available = False

    # ------------------------------------------------------------------
    # Source CRUD
    # ------------------------------------------------------------------

    def upsert_source(self, source: KnowledgeSource) -> str:
        if not source.source_id:
            source.source_id = deterministic_source_id(source.type, source.path)
        if source.type not in VALID_SOURCE_TYPES:
            raise KnowledgeError(f"Invalid source type: {source.type}")
        now = self.self._now()
        if not source.indexed_at:
            source.indexed_at = now
        self._execute(
            """INSERT OR REPLACE INTO knowledge_sources
               (source_id, type, path, hash, version, metadata_json, indexed_at, status, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.source_id,
                source.type,
                source.path,
                source.hash,
                source.version,
                json.dumps(source.metadata_json or {}, ensure_ascii=False),
                source.indexed_at,
                source.status,
                self._project_id,
            ),
        )
        if self._conn:
            self._conn.commit()
        return source.source_id

    def list_sources(self, source_type: str | None = None) -> list[KnowledgeSource]:
        if source_type and source_type not in VALID_SOURCE_TYPES:
            return []
        if source_type:
            rows = self._fetch_all(
                """SELECT source_id, type, path, hash, version, metadata_json, indexed_at, status
                   FROM knowledge_sources
                   WHERE project_id = ? AND type = ?
                   ORDER BY type, path""",
                (self._project_id, source_type),
            )
        else:
            rows = self._fetch_all(
                """SELECT source_id, type, path, hash, version, metadata_json, indexed_at, status
                   FROM knowledge_sources
                   WHERE project_id = ?
                   ORDER BY type, path""",
                (self._project_id,),
            )
        return [_row_to_source(row) for row in rows]

    # ------------------------------------------------------------------
    # Document indexing (incremental by hash)
    # ------------------------------------------------------------------

    def index_document(self, doc: KnowledgeDocument) -> dict:
        if doc.type not in VALID_SOURCE_TYPES:
            raise KnowledgeError(f"Invalid document type: {doc.type}")

        source_id = deterministic_source_id(doc.type, doc.path)
        doc.source_id = source_id
        if not doc.document_id:
            doc.document_id = hashlib.sha256(f"{source_id}|{doc.path}".encode()).hexdigest()

        if not doc.title:
            doc.title = Path(doc.path).name

        doc_hash = compute_hash(doc.content)

        self._ensure_source(source_id, doc.type, doc.path, doc.version)

        result: dict = {
            "action": "indexed",
            "chunks_created": 0,
            "chunks_deleted": 0,
            "source_id": source_id,
        }

        existing = self._fetch_one(
            """SELECT hash, document_id FROM knowledge_documents
               WHERE document_id = ? AND project_id = ?""",
            (doc.document_id, self._project_id),
        )

        if existing:
            old_hash = existing[0]
            if old_hash == doc_hash:
                result["action"] = "skipped"
                return result

            self._delete_chunks_for_source(source_id)
            deleted = self._conn.total_changes if self._conn else 0
            self._execute(
                "DELETE FROM knowledge_documents WHERE document_id = ? AND project_id = ?",
                (doc.document_id, self._project_id),
            )
            result["chunks_deleted"] = deleted
            result["action"] = "reindexed"

        chunks = chunk_text(
            doc.content,
            source_type=doc.type,
            source_id=source_id,
            doc_metadata={
                "title": doc.title,
                "path": doc.path,
                "type": doc.type,
                "version": doc.version,
                **(doc.metadata or {}),
            },
        )
        created = 0
        for ch in chunks:
            self._insert_chunk(ch, source_id, doc.document_id)
            created += 1

        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO knowledge_documents
               (document_id, source_id, title, path, hash, metadata_json, indexed_at, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.document_id,
                source_id,
                doc.title,
                doc.path,
                doc_hash,
                json.dumps(doc.metadata or {}, ensure_ascii=False),
                now,
                self._project_id,
            ),
        )
        self._execute(
            """UPDATE knowledge_sources
               SET hash = ?, indexed_at = ?, status = 'active'
               WHERE source_id = ? AND project_id = ?""",
            (doc_hash, now, source_id, self._project_id),
        )
        if self._conn:
            self._conn.commit()

        result.setdefault("action", "indexed")
        result.setdefault("chunks_deleted", 0)
        result["chunks_created"] = created
        return result

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    def get_source_chunks(self, source_id: str) -> list[KnowledgeChunk]:
        rows = self._fetch_all(
            """SELECT chunk_id, source_id, document_id, content, metadata_json,
                      content_hash, position, token_estimate
               FROM knowledge_chunks
               WHERE source_id = ? AND project_id = ?
               ORDER BY position""",
            (source_id, self._project_id),
        )
        return [_row_to_chunk(row) for row in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: KnowledgeQuery) -> list[KnowledgeResult]:
        if not query.text.strip():
            return []
        return self._search_fts(query) if self._fts_available else self._search_like(query)

    # ------------------------------------------------------------------
    # Index runs (audit)
    # ------------------------------------------------------------------

    def start_run(self, run_id: str) -> None:
        self._execute(
            """INSERT INTO knowledge_index_runs
               (run_id, started_at, sources_scanned, sources_skipped,
                sources_reindexed, chunks_created, chunks_deleted, status, project_id)
               VALUES (?, ?, 0, 0, 0, 0, 0, 'running', ?)""",
            (run_id, self._now(), self._project_id),
        )
        if self._conn:
            self._conn.commit()

    def finish_run(  # noqa: PLR0913, PLR0917
        self,
        run_id: str,
        scanned: int,
        skipped: int,
        reindexed: int,
        chunks_created: int,
        chunks_deleted: int,
    ) -> None:
        self._execute(
            """UPDATE knowledge_index_runs
               SET finished_at = ?,
                   sources_scanned = ?,
                   sources_skipped = ?,
                   sources_reindexed = ?,
                   chunks_created = ?,
                   chunks_deleted = ?,
                   status = 'completed'
               WHERE run_id = ? AND project_id = ?""",
            (
                self._now(),
                scanned,
                skipped,
                reindexed,
                chunks_created,
                chunks_deleted,
                run_id,
                self._project_id,
            ),
        )
        if self._conn:
            self._conn.commit()

    def get_last_run(self) -> dict | None:
        row = self._fetch_one(
            """SELECT run_id, started_at, finished_at, sources_scanned, sources_skipped,
                      sources_reindexed, chunks_created, chunks_deleted, status
               FROM knowledge_index_runs
               WHERE project_id = ?
               ORDER BY started_at DESC
               LIMIT 1""",
            (self._project_id,),
        )
        if not row:
            return None
        return {
            "run_id": row[0],
            "started_at": row[1],
            "finished_at": row[2],
            "sources_scanned": row[3],
            "sources_skipped": row[4],
            "sources_reindexed": row[5],
            "chunks_created": row[6],
            "chunks_deleted": row[7],
            "status": row[8],
        }

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def save_embedding(  # noqa: PLR0913, PLR0917
        self,
        chunk_id: str,
        provider: str,
        model: str,
        vector_dim: int,
        vector_blob: str,
        embedding_hash: str,
    ) -> None:
        self._execute(
            """INSERT OR REPLACE INTO knowledge_embeddings
               (chunk_id, provider, model, vector_dim, vector_blob, embedding_hash,
                created_at, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk_id,
                provider,
                model,
                vector_dim,
                vector_blob,
                embedding_hash,
                self._now(),
                self._project_id,
            ),
        )
        if self._conn:
            self._conn.commit()

    def get_embeddings_by_chunk_ids(self, chunk_ids: list[str]) -> list[dict]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" * len(chunk_ids))
        rows = self._fetch_all(
            f"""SELECT chunk_id, provider, model, vector_dim, vector_blob, embedding_hash
                FROM knowledge_embeddings
                WHERE chunk_id IN ({placeholders}) AND project_id = ?
                ORDER BY chunk_id""",
            tuple(chunk_ids) + (self._project_id,),
        )
        return [
            {
                "chunk_id": row[0],
                "provider": row[1],
                "model": row[2],
                "vector_dim": row[3],
                "vector_blob": row[4],
                "embedding_hash": row[5],
            }
            for row in rows
        ]

    def find_unembedded_chunk_ids(self, chunk_ids: list[str]) -> list[str]:
        if not chunk_ids:
            return []
        placeholders = ", ".join("?" * len(chunk_ids))
        embedded = set(
            row[0]
            for row in self._fetch_all(
                f"""SELECT chunk_id FROM knowledge_embeddings
                    WHERE chunk_id IN ({placeholders}) AND project_id = ?""",
                tuple(chunk_ids) + (self._project_id,),
            )
        )
        return [cid for cid in chunk_ids if cid not in embedded]

    def delete_embeddings_for_source(self, source_id: str) -> None:
        self._execute(
            """DELETE FROM knowledge_embeddings
               WHERE chunk_id IN (
                   SELECT chunk_id FROM knowledge_chunks
                   WHERE source_id = ? AND project_id = ?
               )""",
            (source_id, self._project_id),
        )
        if self._conn:
            self._conn.commit()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def upsert_source_metadata(self, source_id: str, metadata: dict) -> None:
        self._execute(
            """UPDATE knowledge_sources
               SET metadata_json = ?
               WHERE source_id = ? AND project_id = ?""",
            (json.dumps(metadata or {}, ensure_ascii=False), source_id, self._project_id),
        )
        if self._conn:
            self._conn.commit()

    def _ensure_source(self, source_id: str, stype: str, path: str, version: str) -> None:
        existing = self._fetch_one(
            "SELECT 1 FROM knowledge_sources WHERE source_id = ? AND project_id = ?",
            (source_id, self._project_id),
        )
        if existing:
            return
        self._execute(
            """INSERT INTO knowledge_sources
               (source_id, type, path, hash, version, metadata_json, indexed_at, status, project_id)
               VALUES (?, ?, ?, '', ?, '{}', '', 'active', ?)""",
            (source_id, stype, path, version, self._project_id),
        )

    def _search_fts(self, query: KnowledgeQuery) -> list[KnowledgeResult]:
        tokens = query.text.strip().split()
        fts_expr = " OR ".join(f"({_escape_fts_token(t)})" for t in tokens if t)
        if not fts_expr:
            return []

        params: list = [fts_expr, self._project_id]
        type_clause = ""
        if query.source_types:
            placeholders = ", ".join("?" * len(query.source_types))
            type_clause = f" AND ks.type IN ({placeholders})"
            params.extend(query.source_types)

        try:
            rows = self._fetch_all(
                f"""SELECT kc.chunk_id, kc.source_id, kc.document_id, kc.content,
                           kc.metadata_json, kc.content_hash, kc.position,
                           kc.token_estimate
                    FROM (
                        SELECT chunk_id, rank FROM knowledge_fts
                        WHERE knowledge_fts MATCH ?
                    ) fts
                    JOIN knowledge_chunks kc ON fts.chunk_id = kc.chunk_id
                    JOIN knowledge_sources ks ON kc.source_id = ks.source_id
                        AND kc.project_id = ks.project_id
                    WHERE kc.project_id = ?
                        {type_clause}
                    ORDER BY fts.rank
                    LIMIT ?""",
                tuple(params) + (query.limit,),
            )
            return self._rows_to_results(rows)
        except sqlite3.OperationalError:
            return self._search_like(query)

    def _search_like(self, query: KnowledgeQuery) -> list[KnowledgeResult]:
        pattern = f"%{query.text}%"
        where = "kc.content LIKE ? AND kc.project_id = ?"
        params: list = [pattern, self._project_id]

        if query.source_types:
            placeholders = ", ".join("?" * len(query.source_types))
            where += f" AND ks.type IN ({placeholders})"
            params.extend(query.source_types)

        rows = self._fetch_all(
            f"""SELECT kc.chunk_id, kc.source_id, kc.document_id, kc.content,
                       kc.metadata_json, kc.content_hash, kc.position,
                       kc.token_estimate
                FROM knowledge_chunks kc
                JOIN knowledge_sources ks ON kc.source_id = ks.source_id
                    AND kc.project_id = ks.project_id
                WHERE {where}
                ORDER BY length(kc.content) ASC
                LIMIT ?""",
            tuple(params) + (query.limit,),
        )
        return self._rows_to_results(rows)

    def _rows_to_results(self, rows: list[tuple]) -> list[KnowledgeResult]:
        results: list[KnowledgeResult] = []
        for row in rows:
            source = self._fetch_one(
                "SELECT type, path FROM knowledge_sources WHERE source_id = ? AND project_id = ?",
                (row[1], self._project_id),
            )
            source_type = source[0] if source else ""
            source_path = source[1] if source else ""
            results.append(
                KnowledgeResult(
                    chunk_id=row[0],
                    source_id=row[1],
                    source_type=source_type,
                    source_path=source_path,
                    document_id=row[2],
                    content=row[3],
                    position=row[6],
                    content_hash=row[5],
                    token_estimate=row[7],
                    metadata=_parse_json(row[4]),
                )
            )
        return results

    def _delete_chunks_for_source(self, source_id: str) -> None:
        if self._fts_available:
            self._execute(
                "DELETE FROM knowledge_fts WHERE source_id = ?",
                (source_id,),
            )
        self.delete_embeddings_for_source(source_id)
        self._execute(
            "DELETE FROM knowledge_chunks WHERE source_id = ? AND project_id = ?",
            (source_id, self._project_id),
        )

    def _insert_chunk(self, ch: dict, source_id: str, document_id: str) -> None:
        self._execute(
            """INSERT OR REPLACE INTO knowledge_chunks
               (chunk_id, source_id, document_id, content, metadata_json,
                content_hash, position, token_estimate, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ch["chunk_id"],
                source_id,
                document_id,
                ch["content"],
                json.dumps(ch["metadata"], ensure_ascii=False),
                ch["content_hash"],
                ch["position"],
                ch["token_estimate"],
                self._project_id,
            ),
        )
        if self._fts_available:
            self._execute(
                """INSERT INTO knowledge_fts
                   (chunk_id, source_id, document_id, content, project_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    ch["chunk_id"],
                    source_id,
                    document_id,
                    ch["content"],
                    self._project_id,
                ),
            )


def _parse_json(raw: str | None) -> dict:
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _row_to_source(row: tuple) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=row[0],
        type=row[1],
        path=row[2],
        hash=row[3],
        version=row[4],
        metadata_json=_parse_json(row[5]),
        indexed_at=row[6],
        status=row[7],
    )


def _row_to_chunk(row: tuple) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=row[0],
        source_id=row[1],
        document_id=row[2],
        content=row[3],
        metadata=_parse_json(row[4]),
        content_hash=row[5],
        position=row[6],
        token_estimate=row[7],
    )


def _escape_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'
