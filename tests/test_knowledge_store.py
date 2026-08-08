"""Tests for SQLiteKnowledgeStore — schema, incremental indexing, search, isolation."""

from aios.knowledge.models import KnowledgeDocument, KnowledgeQuery
from aios.knowledge.store import SQLiteKnowledgeStore, deterministic_source_id


class TestSchema:
    def test_schema_created(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "knowledge_sources" in tables
        assert "knowledge_documents" in tables
        assert "knowledge_chunks" in tables
        assert "knowledge_index_runs" in tables
        store.close()

    def test_schema_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.close()
        store.open()
        assert store.is_open()
        store.close()


class TestIndexDocument:
    def test_index_initial(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/test.md",
            content="# Hello\n\nWorld content here.\n",
            type="documentation",
        )
        result = store.index_document(doc)

        assert result["action"] == "indexed"
        assert result["chunks_created"] > 0

        source_id = deterministic_source_id("documentation", "docs/test.md")
        sources = store.list_sources("documentation")
        assert len(sources) == 1
        assert sources[0].source_id == source_id

        chunks = store.get_source_chunks(source_id)
        assert len(chunks) == result["chunks_created"]
        assert all(ch.content for ch in chunks)
        assert all(ch.chunk_id for ch in chunks)

        store.close()

    def test_reindex_skip_same_hash(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        content = "# Title\n\nSome text here.\n"
        doc = KnowledgeDocument(
            path="docs/keep.md",
            content=content,
            type="documentation",
        )
        first = store.index_document(doc)
        assert first["action"] == "indexed"
        created_first = first["chunks_created"]

        second = store.index_document(doc)
        assert second["action"] == "skipped"
        assert second["chunks_created"] == 0

        source_id = deterministic_source_id("documentation", "docs/keep.md")
        chunks = store.get_source_chunks(source_id)
        assert len(chunks) == created_first

        store.close()

    def test_reindex_content_changed(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/change.md",
            content="# Old\n\nOld content.\n",
            type="documentation",
        )
        first = store.index_document(doc)
        assert first["action"] == "indexed"

        doc.content = "# New\n\nNew content here.\nAdditional line.\n"
        second = store.index_document(doc)
        assert second["action"] == "reindexed"
        assert second["chunks_deleted"] > 0
        new_chunks = second["chunks_created"]

        source_id = deterministic_source_id("documentation", "docs/change.md")
        chunks = store.get_source_chunks(source_id)
        assert len(chunks) == new_chunks

        store.close()

    def test_no_duplicate_chunks_on_reindex(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/dup.md",
            content="# No Dupe\n\nContent.\n",
            type="documentation",
        )
        store.index_document(doc)
        store.index_document(doc)
        store.index_document(doc)

        source_id = deterministic_source_id("documentation", "docs/dup.md")
        chunks = store.get_source_chunks(source_id)
        assert len(chunks) > 0

        rows = store._fetch_all(
            "SELECT chunk_id, COUNT(*) FROM knowledge_chunks "
            "WHERE source_id = ? AND project_id = ? "
            "GROUP BY chunk_id HAVING COUNT(*) > 1",
            (source_id, "project-1"),
        )
        assert len(rows) == 0

        store.close()


class TestProjectIsolation:
    def test_projects_isolated(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = SQLiteKnowledgeStore(db, "project-a")
        store_b = SQLiteKnowledgeStore(db, "project-b")
        store_a.open()
        store_b.open()

        doc_a = KnowledgeDocument(
            path="docs/a.md",
            content="# Project A\n\nContent A.\n",
            type="documentation",
        )
        doc_b = KnowledgeDocument(
            path="docs/b.md",
            content="# Project B\n\nContent B.\n",
            type="documentation",
        )
        store_a.index_document(doc_a)
        store_b.index_document(doc_b)

        assert len(store_a.list_sources()) == 1
        assert len(store_b.list_sources()) == 1
        assert store_a.list_sources()[0].path == "docs/a.md"
        assert store_b.list_sources()[0].path == "docs/b.md"

        store_a.close()
        store_b.close()


class TestSearch:
    def test_search_fts(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        doc = KnowledgeDocument(
            path="docs/auth.md",
            content="# Authentication\n\nHow to implement authentication flows.\n",
            type="documentation",
        )
        store.index_document(doc)

        results = store.search(KnowledgeQuery(text="authentication"))
        assert len(results) > 0
        assert any("authentication" in r.content.lower() for r in results)

        results_none = store.search(KnowledgeQuery(text="zzz_nonexistent_zzz"))
        assert len(results_none) == 0

        store.close()

    def test_search_filters_by_type(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        store.index_document(
            KnowledgeDocument(
                path="docs/readme.md",
                content="# Docs\n\nDocumentation.\n",
                type="documentation",
            )
        )
        store.index_document(
            KnowledgeDocument(
                path="docs/decisions/adr1.md",
                content="# ADR\n\nDecision.\n",
                type="adr",
            )
        )

        results = store.search(KnowledgeQuery(text="documentation", source_types=["documentation"]))
        assert len(results) > 0
        store.close()

    def test_search_empty_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        results = store.search(KnowledgeQuery(text="  "))
        assert results == []
        store.close()


class TestSources:
    def test_list_all_and_filtered(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        store.index_document(
            KnowledgeDocument(
                path="docs/one.md",
                content="# One\n",
                type="documentation",
            )
        )
        store.index_document(
            KnowledgeDocument(
                path="src/main.py",
                content="def main(): pass\n",
                type="code",
            )
        )

        all_sources = store.list_sources()
        assert len(all_sources) == 2

        doc_sources = store.list_sources("documentation")
        assert len(doc_sources) == 1
        assert doc_sources[0].type == "documentation"

        code_sources = store.list_sources("code")
        assert len(code_sources) == 1
        assert code_sources[0].type == "code"

        invalid = store.list_sources("nonexistent")
        assert invalid == []

        store.close()


class TestIndexRuns:
    def test_run_lifecycle(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        store.start_run("run-001")
        store.finish_run("run-001", 10, 5, 3, 20, 5)

        last = store.get_last_run()
        assert last is not None
        assert last["run_id"] == "run-001"
        assert last["sources_scanned"] == 10
        assert last["sources_skipped"] == 5
        assert last["sources_reindexed"] == 3
        assert last["chunks_created"] == 20
        assert last["chunks_deleted"] == 5
        assert last["status"] == "completed"

        store.close()

    def test_get_last_run_empty(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        assert store.get_last_run() is None
        store.close()


class TestClosedStore:
    def test_queries_on_closed(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.close()
        assert store.list_sources() == []
        assert store.search(KnowledgeQuery(text="test")) == []
