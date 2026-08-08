"""Tests for ContextBudget and ContextSelector."""

from aios.knowledge.models import KnowledgeDocument, KnowledgeResult
from aios.knowledge.store import SQLiteKnowledgeStore
from aios.retrieval.providers import FakeEmbeddingProvider
from aios.retrieval.retrievers import KeywordRetriever, VectorRetriever
from aios.retrieval.selector import ContextBudget, ContextSelector


def _make_result(chunk_id: str, content: str, token_est: int = 10) -> KnowledgeResult:
    return KnowledgeResult(
        chunk_id=chunk_id,
        source_id="sid",
        source_type="documentation",
        source_path="docs/test.md",
        content=content,
        content_hash="fake-hash",
        position=0,
        token_estimate=token_est,
    )


class TestContextBudget:
    def test_default_budgets(self):
        budget = ContextBudget()
        assert budget.for_agent("planner") == 3000
        assert budget.for_agent("research") == 5000
        assert budget.for_agent("reviewer") == 2000

    def test_override_single(self):
        budget = ContextBudget(overrides={"planner": 1500})
        assert budget.for_agent("planner") == 1500
        assert budget.for_agent("research") == 5000

    def test_override_multiple(self):
        budget = ContextBudget(overrides={"planner": 1000, "reviewer": 800})
        assert budget.for_agent("planner") == 1000
        assert budget.for_agent("reviewer") == 800
        assert budget.for_agent("research") == 5000

    def test_unknown_agent_returns_default(self):
        budget = ContextBudget()
        assert budget.for_agent("unknown_agent") == 3000

    def test_empty_overrides(self):
        budget = ContextBudget(overrides={})
        assert budget.for_agent("planner") == 3000


class TestContextSelector:
    def _selector(self, store, budget=None):
        return ContextSelector(
            retriever=KeywordRetriever(store),
            budget=budget or ContextBudget(),
        )

    def test_selection_within_budget(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/test.md",
                content="Token counting is important for context budgets.",
                type="documentation",
            )
        )

        selector = self._selector(store, budget=ContextBudget(overrides={"planner": 100}))
        result = selector.select("token context budget", agent="planner", k=5)

        assert result.selected_count > 0
        assert result.tokens_after <= 100
        assert result.tokens_before > 0
        assert len(result.chunks) == result.selected_count
        store.close()

    def test_never_exceeds_budget(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        text = "Token budget enforcement. " * 50
        store.index_document(
            KnowledgeDocument(
                path="docs/large.md",
                content=f"# Large\n\n{text}\n",
                type="documentation",
            )
        )

        selector = self._selector(store, budget=ContextBudget(overrides={"planner": 10}))
        result = selector.select("token enforcement", agent="planner", k=10)

        assert result.tokens_after <= 10
        assert result.selected_count <= 10
        store.close()

    def test_empty_results_graceful_fallback(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()

        selector = self._selector(store)
        result = selector.select("nonexistent query zzz", agent="planner", k=5)

        assert result.selected_count == 0
        assert result.chunks == []
        assert result.tokens_before == 0
        assert result.tokens_after == 0
        assert result.compression_ratio == 0.0
        assert len(result.prompt_context) == 0
        store.close()

    def test_per_agent_budgets(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/test.md",
                content="Machine learning requires good data.",
                type="documentation",
            )
        )

        budget = ContextBudget(overrides={"planner": 5, "research": 200})
        selector = self._selector(store, budget=budget)

        result_p = selector.select("machine learning", agent="planner", k=5)
        assert result_p.tokens_after <= 5

        result_r = selector.select("machine learning", agent="research", k=5)
        assert result_r.tokens_after <= 200

        store.close()

    def test_metrics_recorded(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/test.md",
                content="Context metrics test data.",
                type="documentation",
            )
        )

        selector = self._selector(store)
        result = selector.select("metrics", agent="planner", k=10)

        assert result.retrieval_latency_ms >= 0
        assert result.chunks_retrieved > 0
        assert result.chunks_selected == result.selected_count
        assert result.tokens_before > 0
        assert result.tokens_after > 0
        assert 0 <= result.compression_ratio <= 1.0
        store.close()

    def test_justification_per_chunk(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/test.md",
                content="Justification test content for chunk selection.",
                type="documentation",
            )
        )

        selector = self._selector(store)
        result = selector.select("justification test", agent="research", k=5)

        if result.chunks:
            assert result.chunks[0].justification
            assert "score" in result.chunks[0].justification.lower()

        store.close()

    def test_diversity_dedupe(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        for i in range(5):
            store.index_document(
                KnowledgeDocument(
                    path=f"docs/file{i}.md",
                    content="# Section\n\nNearly identical content for testing.\n",
                    type="documentation",
                )
            )

        selector = self._selector(store, budget=ContextBudget(overrides={"research": 500}))
        result = selector.select("testing", agent="research", k=10)

        sources = {c.result.source_path for c in result.chunks}
        assert len(sources) == len(result.chunks)
        store.close()

    def test_prompt_context_format(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/format.md",
                content="# Format\n\nThis is formatted output.",
                type="documentation",
            )
        )

        selector = self._selector(store)
        result = selector.select("format", agent="planner", k=5)

        if result.selected_count > 0:
            assert "[Knowledge]" in result.prompt_context or "source=" in result.prompt_context

        store.close()

    def test_vector_fallback_to_keyword(self, tmp_path):
        db = tmp_path / "test.db"
        store = SQLiteKnowledgeStore(db, "project-1")
        store.open()
        store.index_document(
            KnowledgeDocument(
                path="docs/fallback.md",
                content="Fallback test for vector to keyword path.",
                type="documentation",
            )
        )

        provider = FakeEmbeddingProvider(dims=4)
        selector = ContextSelector(
            retriever=VectorRetriever(store, provider),
            fallback_retriever=KeywordRetriever(store),
            budget=ContextBudget(),
        )

        result = selector.select("fallback test", agent="planner", k=5)
        assert result.selected_count > 0

        store.close()
