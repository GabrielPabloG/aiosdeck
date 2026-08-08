"""Knowledge Engine — indexes and queries structured project knowledge."""

from __future__ import annotations

import hashlib
import json
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
from aios.retrieval.providers import EmbeddingProvider
from aios.retrieval.retrievers import KeywordRetriever, VectorRetriever
from aios.retrieval.selector import ContextBudget, ContextSelector, SelectionResult

logger = logging.getLogger("aios.knowledge")


class KnowledgeEngine:
    name = "knowledge"

    def __init__(
        self,
        project_path: Path | None = None,
        db_path: str | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = db_path or str(self._project_path / ".aios" / "memory.db")
        self._store: SQLiteKnowledgeStore | None = None
        self._embedding_provider = embedding_provider

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
                metadata=candidate.metadata,
            )
            try:
                result = self._store.index_document(doc)
                if doc.metadata:
                    self._store.upsert_source_metadata(doc.source_id, doc.metadata)
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
    # Embedding
    # ------------------------------------------------------------------

    def embed_indexed(self, model: str = "", dimensions: int = 0) -> dict:
        provider = self._embedding_provider
        if provider is None or self._store is None:
            return {"embedded": 0, "skipped": 0, "status": "no_provider"}

        if not provider.available():
            return {"embedded": 0, "skipped": 0, "status": "provider_unavailable"}

        sources = self._store.list_sources()
        all_chunk_ids: list[str] = []
        for source in sources:
            chunks = self._store.get_source_chunks(source.source_id)
            all_chunk_ids.extend(ch.chunk_id for ch in chunks)

        if not all_chunk_ids:
            return {"embedded": 0, "skipped": 0, "status": "no_chunks"}

        unembedded = self._store.find_unembedded_chunk_ids(all_chunk_ids)
        if not unembedded:
            return {"embedded": 0, "skipped": len(all_chunk_ids), "status": "up_to_date"}

        chunk_map: dict[str, tuple[str, str]] = {}
        for source in sources:
            for ch in self._store.get_source_chunks(source.source_id):
                if ch.chunk_id in unembedded:
                    chunk_map[ch.chunk_id] = (ch.content, ch.content_hash)

        chunks_to_embed = [(cid, chunk_map[cid][0]) for cid in unembedded if cid in chunk_map]
        model_name = model or getattr(provider, "_model", "") or "<unknown>"

        batch_size = min(32, max(1, len(chunks_to_embed)))
        embedded = 0
        skipped = 0

        for i in range(0, len(chunks_to_embed), batch_size):
            batch = chunks_to_embed[i : i + batch_size]
            texts = [t for _, t in batch]
            try:
                vectors = provider.embed(texts)
            except Exception:
                logger.warning("Embedding batch failed, stopping")
                break

            dims = provider.dimensions()
            for j, (chunk_id, _) in enumerate(batch):
                if j >= len(vectors):
                    break
                content_hash = chunk_map[chunk_id][1]
                emb_hash = hashlib.sha256(
                    f"{content_hash}|{provider.name}|{model_name}".encode()
                ).hexdigest()
                self._store.save_embedding(
                    chunk_id=chunk_id,
                    provider=provider.name,
                    model=model_name,
                    vector_dim=dims,
                    vector_blob=json.dumps(vectors[j]),
                    embedding_hash=emb_hash,
                )
                embedded += 1

        return {"embedded": embedded, "skipped": skipped, "status": "ok"}

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve_raw(
        self,
        query: str,
        *,
        limit: int = 50,
        source_types: list[str] | None = None,
    ):
        if self._store is None:
            return []
        kw = KeywordRetriever(self._store)
        filters: dict = {}
        if source_types:
            filters["source_types"] = source_types
        return kw.retrieve(query, k=limit, filters=filters)

    def retrieve(  # noqa: PLR0913
        self,
        query: str,
        *,
        agent: str = "research",
        limit: int = 20,
        use_vector: bool = False,
        budget_overrides: dict[str, int] | None = None,
    ) -> SelectionResult:
        if self._store is None:
            return SelectionResult()

        budget = ContextBudget(overrides=budget_overrides or {})
        kw = KeywordRetriever(self._store)
        fallback = None

        if use_vector and self._embedding_provider is not None:
            if self._embedding_provider.available():
                vr = VectorRetriever(self._store, self._embedding_provider)
                fallback = kw
                retriever = vr
            else:
                logger.info("Vector retriever requested but provider unavailable; using keyword")
                retriever = kw
        else:
            retriever = kw

        selector = ContextSelector(
            retriever=retriever,
            fallback_retriever=fallback,
            budget=budget,
        )
        return selector.select(query, agent=agent, k=limit)

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
