"""Tests for knowledge_embeddings table — CRUD, isolation, incremental re-embed."""

import hashlib

from aios.knowledge.models import KnowledgeDocument
from aios.knowledge.store import SQLiteKnowledgeStore, deterministic_source_id


def _embedding_hash(content_hash: str, provider: str, model: str) -> str:
    return hashlib.sha256(f"{content_hash}|{provider}|{model}".encode()).hexdigest()


class TestEmbeddingsTable:
    def test_table_exists(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "knowledge_embeddings" in tables
        store.close()

    def test_save_and_get(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/test.md",
            content="# Hello\n\nWorld.\n",
            type="documentation",
        )
        store.index_document(doc)
        source_id = deterministic_source_id("documentation", "docs/test.md")
        chunks = store.get_source_chunks(source_id)
        assert len(chunks) == 1

        chunk = chunks[0]
        store.save_embedding(
            chunk_id=chunk.chunk_id,
            provider="ollama",
            model="nomic-embed-text",
            vector_dim=4,
            vector_blob="[0.1,0.2,0.3,0.4]",
            embedding_hash="abc123",
        )

        embs = store.get_embeddings_by_chunk_ids([chunk.chunk_id])
        assert len(embs) == 1
        assert embs[0]["chunk_id"] == chunk.chunk_id
        assert embs[0]["provider"] == "ollama"
        assert embs[0]["model"] == "nomic-embed-text"
        assert embs[0]["vector_dim"] == 4
        assert embs[0]["vector_blob"] == "[0.1,0.2,0.3,0.4]"
        assert embs[0]["embedding_hash"] == "abc123"

        store.close()

    def test_upsert_replaces(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/test.md",
            content="content",
            type="documentation",
        )
        store.index_document(doc)
        chunks = store.get_source_chunks(deterministic_source_id("documentation", "docs/test.md"))
        chunk_id = chunks[0].chunk_id

        store.save_embedding(chunk_id, "ollama", "m1", 4, "[1,2,3,4]", "h1")
        store.save_embedding(chunk_id, "ollama", "m1", 4, "[5,6,7,8]", "h2")

        embs = store.get_embeddings_by_chunk_ids([chunk_id])
        assert len(embs) == 1
        assert embs[0]["vector_blob"] == "[5,6,7,8]"
        assert embs[0]["embedding_hash"] == "h2"

        store.close()

    def test_project_isolation(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = SQLiteKnowledgeStore(db, "project-a")
        store_b = SQLiteKnowledgeStore(db, "project-b")
        store_a.open()
        store_b.open()

        doc_a = KnowledgeDocument(path="a.md", content="A", type="documentation")
        doc_b = KnowledgeDocument(path="b.md", content="B", type="documentation")
        store_a.index_document(doc_a)
        store_b.index_document(doc_b)

        chunks_a = store_a.get_source_chunks(deterministic_source_id("documentation", "a.md"))
        store_a.save_embedding(chunks_a[0].chunk_id, "p", "m", 4, "[1]", "h")
        store_b.save_embedding(
            store_b.get_source_chunks(deterministic_source_id("documentation", "b.md"))[0].chunk_id,
            "p",
            "m",
            4,
            "[2]",
            "h",
        )

        assert len(store_a.get_embeddings_by_chunk_ids([chunks_a[0].chunk_id])) == 1
        store_a.close()
        store_b.close()

    def test_delete_by_source(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/remove.md",
            content="# Remove\n\nContent.\n",
            type="documentation",
        )
        source_id = deterministic_source_id("documentation", "docs/remove.md")
        store.index_document(doc)
        chunks = store.get_source_chunks(source_id)
        store.save_embedding(chunks[0].chunk_id, "p", "m", 4, "[1]", "h")

        store.delete_embeddings_for_source(source_id)
        assert store.get_embeddings_by_chunk_ids([c.chunk_id for c in chunks]) == []

        store.close()

    def test_find_unembedded_chunks(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc1 = KnowledgeDocument(path="docs/a.md", content="# A\n", type="documentation")
        doc2 = KnowledgeDocument(path="docs/b.md", content="# B\n", type="documentation")
        store.index_document(doc1)
        store.index_document(doc2)

        sid_a = deterministic_source_id("documentation", "docs/a.md")
        sid_b = deterministic_source_id("documentation", "docs/b.md")
        chunks_a = store.get_source_chunks(sid_a)
        chunks_b = store.get_source_chunks(sid_b)

        all_ids = [c.chunk_id for c in chunks_a + chunks_b]
        assert len(all_ids) == 2

        store.save_embedding(chunks_a[0].chunk_id, "p", "m", 4, "[1]", "h1")

        unembedded = store.find_unembedded_chunk_ids(all_ids)
        assert unembedded == [chunks_b[0].chunk_id]

        store.close()

    def test_reindex_deletes_embeddings(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/change.md",
            content="# A\n\nContent.\n",
            type="documentation",
        )
        source_id = deterministic_source_id("documentation", "docs/change.md")
        store.index_document(doc)
        chunks = store.get_source_chunks(source_id)
        store.save_embedding(chunks[0].chunk_id, "p", "m", 4, "[1]", "h")

        doc.content = "# B\n\nChanged.\n"
        store.index_document(doc)

        assert (
            store.get_embeddings_by_chunk_ids(
                [c.chunk_id for c in store.get_source_chunks(source_id)]
            )
            == []
        )

        store.close()

    def test_get_embeddings_empty(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        assert store.get_embeddings_by_chunk_ids(["nonexistent"]) == []
        store.close()
