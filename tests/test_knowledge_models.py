"""Tests for knowledge contracts — valid defaults, to_dict, type enums."""

from aios.knowledge.models import (
    VALID_SOURCE_TYPES,
    IndexSummary,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeQuery,
    KnowledgeResult,
    KnowledgeSource,
)


class TestKnowledgeSource:
    def test_defaults(self):
        s = KnowledgeSource()
        assert s.source_id == ""
        assert s.type == "skill"
        assert s.path == ""
        assert s.hash == ""
        assert s.version == "1"
        assert s.metadata_json == {}
        assert s.indexed_at == ""
        assert s.status == "active"

    def test_to_dict(self):
        s = KnowledgeSource(
            source_id="src-1",
            type="adr",
            path="docs/decisions/ADR.md",
            hash="abc123",
            version="2",
        )
        d = s.to_dict()
        assert d["source_id"] == "src-1"
        assert d["type"] == "adr"
        assert d["path"] == "docs/decisions/ADR.md"
        assert d["hash"] == "abc123"
        assert d["version"] == "2"
        assert d["status"] == "active"


class TestKnowledgeDocument:
    def test_defaults(self):
        d = KnowledgeDocument()
        assert d.document_id == ""
        assert d.source_id == ""
        assert d.title == ""
        assert d.path == ""
        assert d.content == ""
        assert d.type == "documentation"
        assert d.version == "1"
        assert d.metadata == {}

    def test_to_dict(self):
        d = KnowledgeDocument(title="Test Doc", path="test.md", type="adr")
        result = d.to_dict()
        assert result["title"] == "Test Doc"
        assert result["type"] == "adr"


class TestKnowledgeChunk:
    def test_defaults(self):
        c = KnowledgeChunk()
        assert c.chunk_id == ""
        assert c.content == ""
        assert c.position == 0
        assert c.token_estimate == 0
        assert c.embedding is None

    def test_to_dict(self):
        c = KnowledgeChunk(chunk_id="c1", content="hello", position=1, token_estimate=5)
        d = c.to_dict()
        assert d["chunk_id"] == "c1"
        assert d["content"] == "hello"
        assert d["position"] == 1
        assert d["token_estimate"] == 5


class TestKnowledgeQuery:
    def test_defaults(self):
        q = KnowledgeQuery()
        assert q.text == ""
        assert q.limit == 20
        assert q.source_types is None

    def test_with_filters(self):
        q = KnowledgeQuery(text="auth", limit=5, source_types=["adr", "documentation"])
        assert q.text == "auth"
        assert q.limit == 5
        assert q.source_types == ["adr", "documentation"]


class TestKnowledgeResult:
    def test_defaults(self):
        r = KnowledgeResult()
        assert r.source_id == ""
        assert r.content == ""

    def test_to_dict(self):
        r = KnowledgeResult(source_id="s1", source_type="code", content="print(1)")
        d = r.to_dict()
        assert d["source_id"] == "s1"
        assert d["source_type"] == "code"
        assert d["content"] == "print(1)"


class TestIndexSummary:
    def test_defaults(self):
        s = IndexSummary()
        assert s.run_id == ""
        assert s.scanned == 0
        assert s.skipped == 0
        assert s.reindexed == 0
        assert s.chunks_created == 0
        assert s.chunks_deleted == 0

    def test_to_dict(self):
        s = IndexSummary(run_id="r1", scanned=10, skipped=5, reindexed=3, chunks_created=25)
        d = s.to_dict()
        assert d["run_id"] == "r1"
        assert d["scanned"] == 10
        assert d["skipped"] == 5


class TestValidSourceTypes:
    def test_all_types_valid(self):
        for t in VALID_SOURCE_TYPES:
            s = KnowledgeSource(type=t)
            assert s.type == t

    def test_valid_types_tuple(self):
        expected = ("skill", "documentation", "adr", "code", "research", "memory", "project_dna")
        assert expected == VALID_SOURCE_TYPES
