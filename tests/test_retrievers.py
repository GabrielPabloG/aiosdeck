"""Tests for Retriever protocols, KeywordRetriever, VectorRetriever, and fallback."""

import json

from aios.knowledge.models import KnowledgeDocument
from aios.knowledge.store import SQLiteKnowledgeStore, deterministic_source_id
from aios.retrieval.providers import FakeEmbeddingProvider
from aios.retrieval.retrievers import (
    KeywordRetriever,
    Retriever,
    ScoredResult,
    VectorRetriever,
)


def _populate_store(store: SQLiteKnowledgeStore) -> None:
    store.index_document(
        KnowledgeDocument(
            path="docs/auth.md",
            content="# Authentication\n\nImplement OAuth2 flow for user login.\n",
            type="documentation",
        )
    )
    store.index_document(
        KnowledgeDocument(
            path="docs/database.md",
            content="# Database\n\nPostgreSQL connection pooling configuration.\n",
            type="documentation",
        )
    )
    store.index_document(
        KnowledgeDocument(
            path="src/auth.py",
            content="def authenticate(user: str, password: str) -> bool:\n    pass\n",
            type="code",
        )
    )


class TestRetrieverProtocol:
    def test_keyword_retriever_conforms(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        retriever: Retriever = KeywordRetriever(store)
        results = retriever.retrieve("authentication", k=10)

        assert len(results) > 0
        assert all(isinstance(r, ScoredResult) for r in results)
        assert all(hasattr(r, "score") for r in results)
        assert results[0].score >= results[-1].score

        store.close()

    def test_vector_retriever_conforms(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        provider = FakeEmbeddingProvider(dims=4)
        retriever: Retriever = VectorRetriever(store, provider)
        results = retriever.retrieve("authentication", k=5)
        assert all(isinstance(r, ScoredResult) for r in results)

        store.close()


class TestKeywordRetriever:
    def test_retrieve_returns_scored_results(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        retriever = KeywordRetriever(store)
        results = retriever.retrieve("authentication flow", k=10)

        assert len(results) > 0
        for r in results:
            assert 0.0 <= r.score <= 1.0
            assert r.result.content
            assert r.result.source_type

        store.close()

    def test_retrieve_no_match(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        retriever = KeywordRetriever(store)
        results = retriever.retrieve("zzz_nonexistent_term_zzz", k=10)
        assert results == []

        store.close()

    def test_retrieve_empty_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(path="docs/x.md", content="content", type="documentation")
        )

        retriever = KeywordRetriever(store)
        assert retriever.retrieve("", k=5) == []
        assert retriever.retrieve("  ", k=5) == []

        store.close()

    def test_respects_limit(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        retriever = KeywordRetriever(store)
        results = retriever.retrieve("database auth", k=1)
        assert len(results) <= 1

        store.close()


class TestVectorRetriever:
    def test_retrieve_with_fake_provider(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        provider = FakeEmbeddingProvider(dims=8)
        source_id = deterministic_source_id("documentation", "docs/auth.md")
        chunks = store.get_source_chunks(source_id)
        assert len(chunks) > 0

        chunk_content = chunks[0].content
        vec = provider.embed([chunk_content])[0]

        store.save_embedding(
            chunk_id=chunks[0].chunk_id,
            provider=provider.name,
            model="fake",
            vector_dim=8,
            vector_blob=json.dumps(vec),
            embedding_hash="test-hash",
        )

        retriever = VectorRetriever(store, provider)
        results = retriever.retrieve(chunk_content, k=5)

        assert len(results) > 0
        assert all(0.0 <= r.score <= 1.0 for r in results)

        store.close()

    def test_fallback_when_no_embeddings(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        provider = FakeEmbeddingProvider(dims=4)
        retriever = VectorRetriever(store, provider)
        results = retriever.retrieve("query", k=5)
        assert results == []

        store.close()

    def test_empty_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        provider = FakeEmbeddingProvider(dims=4)
        retriever = VectorRetriever(store, provider)
        assert retriever.retrieve("", k=5) == []
        store.close()


class TestRetrieverFallback:
    def test_keyword_works_standalone(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        retriever = KeywordRetriever(store)
        results = retriever.retrieve("authentication", k=5)
        assert len(results) > 0
        store.close()

    def test_vector_graceful_without_embeddings(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        _populate_store(store)

        provider = FakeEmbeddingProvider(dims=4)
        retriever = VectorRetriever(store, provider)
        results = retriever.retrieve("anything", k=5)
        assert results == []
        store.close()
