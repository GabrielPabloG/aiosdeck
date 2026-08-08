"""Knowledge Engine — indexes and queries structured project knowledge."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from aios.knowledge.discovery import discover_sources
from aios.knowledge.models import (
    IndexSummary,
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSource,
)
from aios.knowledge.store import SQLiteKnowledgeStore

logger = logging.getLogger("aios.knowledge")


class KnowledgeEngine:
    name = "knowledge"

    def __init__(self, project_path: Path | None = None, db_path: str | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = db_path or str(self._project_path / ".aios" / "memory.db")
        self._store: SQLiteKnowledgeStore | None = None

    def initialize(self) -> None:
        try:
            self._store = SQLiteKnowledgeStore(Path(self._db_path), self._project_id)
            self._store.open()
        except KnowledgeError as exc:
            self._store = None
            raise RuntimeError(str(exc)) from exc

    def health_check(self) -> bool:
        if self._store is None:
            return True
        return self._store.is_open()

    def shutdown(self) -> None:
        if self._store:
            self._store.close()
            self._store = None

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index(self) -> IndexSummary:
        if self._store is None:
            raise KnowledgeError("Store not initialized")

        run_id = uuid.uuid4().hex[:12]
        self._store.start_run(run_id)

        candidates = discover_sources(self._project_path)
        scanned = 0
        skipped = 0
        reindexed = 0
        chunks_created = 0
        chunks_deleted = 0

        for candidate in candidates:
            scanned += 1
            file_path = self._project_path / candidate.path
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                logger.warning("Cannot read: %s", candidate.path)
                continue

            doc = KnowledgeDocument(
                path=candidate.path,
                content=content,
                type=candidate.type,
                version=candidate.version,
            )
            try:
                result = self._store.index_document(doc)
                if result["action"] == "skipped":
                    skipped += 1
                else:
                    reindexed += 1
                chunks_created += result.get("chunks_created", 0)
                chunks_deleted += result.get("chunks_deleted", 0)
            except KnowledgeError:
                logger.warning("Index failed: %s", candidate.path)

        self._store.finish_run(run_id, scanned, skipped, reindexed, chunks_created, chunks_deleted)

        return IndexSummary(
            run_id=run_id,
            scanned=scanned,
            skipped=skipped,
            reindexed=reindexed,
            chunks_created=chunks_created,
            chunks_deleted=chunks_deleted,
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, text: str, *, limit: int = 20, source_types: list[str] | None = None
    ) -> list[KnowledgeResult]:
        if self._store is None:
            return []
        return self._store.search(KnowledgeQuery(text=text, limit=limit, source_types=source_types))

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def list_sources(self, source_type: str | None = None) -> list[KnowledgeSource]:
        if self._store is None:
            return []
        return self._store.list_sources(source_type)
