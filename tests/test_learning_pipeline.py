"""Pipeline tests: approve gating, ingest blocking, traceability, integration."""

import tempfile
from pathlib import Path

import pytest

from aios.learning.engine import LearningEngine
from aios.learning.models import LearningCandidate
from aios.memory.engine import MemoryEngine


def _tmp_db() -> str:
    return str(Path(tempfile.mkdtemp()) / "test_pipeline.db")


class TestIngestBlocking:
    def test_ingest_blocked_on_draft(self) -> None:
        db = _tmp_db()
        engine = LearningEngine(project_path=Path("/tmp/test"), db_path=db)
        engine.initialize()

        store = engine.get_store()
        assert store is not None
        cid = store.insert_candidate(
            LearningCandidate(
                content="test pattern",
                suggested_type="pattern",
                confidence=0.85,
                risk_level="low",
                dedupe_hash="block1",
                state="draft",
            )
        )
        with pytest.raises(RuntimeError, match="must be approved"):
            engine.ingest(cid)
        engine.shutdown()

    def test_ingest_blocked_on_scored(self) -> None:
        db = _tmp_db()
        engine = LearningEngine(project_path=Path("/tmp/test"), db_path=db)
        engine.initialize()

        store = engine.get_store()
        assert store is not None
        cid = store.insert_candidate(
            LearningCandidate(
                content="test",
                dedupe_hash="block2",
                state="scored",
            )
        )
        with pytest.raises(RuntimeError, match="must be approved"):
            engine.ingest(cid)
        engine.shutdown()

    def test_ingest_blocked_on_rejected(self) -> None:
        db = _tmp_db()
        engine = LearningEngine(project_path=Path("/tmp/test"), db_path=db)
        engine.initialize()

        store = engine.get_store()
        assert store is not None
        cid = store.insert_candidate(
            LearningCandidate(
                content="test",
                dedupe_hash="block3",
                state="rejected",
            )
        )
        with pytest.raises(RuntimeError, match="must be approved"):
            engine.ingest(cid)
        engine.shutdown()

    def test_ingest_blocked_without_memory_engine(self) -> None:
        db = _tmp_db()
        engine = LearningEngine(project_path=Path("/tmp/test"), db_path=db)
        engine.initialize()

        store = engine.get_store()
        assert store is not None
        cid = store.insert_candidate(
            LearningCandidate(
                content="test",
                dedupe_hash="block4",
                state="approved",
            )
        )
        with pytest.raises(RuntimeError, match="Memory engine not available"):
            engine.ingest(cid)
        engine.shutdown()

    def test_ingest_requires_nonexistent_candidate(self) -> None:
        db = _tmp_db()
        engine = LearningEngine(project_path=Path("/tmp/test"), db_path=db)
        engine.initialize()
        with pytest.raises(RuntimeError, match="not found"):
            engine.ingest(99999)
        engine.shutdown()


class TestIngestAfterApproval:
    @pytest.fixture
    def engines(self):
        db = _tmp_db()
        project_path = Path(tempfile.mkdtemp())
        memory = MemoryEngine(project_path=project_path, db_path=db)
        memory.initialize()

        engine = LearningEngine(
            project_path=project_path,
            db_path=db,
            memory=memory,
        )
        engine.initialize()
        yield engine, memory
        engine.shutdown()
        memory.shutdown()

    def test_full_pipeline_convention(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="Use snake_case for all Python function names",
                suggested_type="convention",
                confidence=0.9,
                risk_level="low",
                dedupe_hash="pipe-conv",
            )
        )

        engine.approve(cid)
        version = engine.ingest(cid)
        assert version == 1

        candidate = engine.get_candidate(cid)
        assert candidate.state == "ingested"
        assert candidate.ingest_version == 1
        assert candidate.ingested_memory_id != ""

        knowledge = memory.recall()
        assert len(knowledge.conventions) >= 1
        assert any("snake_case" in c.rule for c in knowledge.conventions)

    def test_full_pipeline_pattern(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="Repository pattern for data access",
                suggested_type="pattern",
                confidence=0.85,
                risk_level="low",
                dedupe_hash="pipe-pattern",
            )
        )

        engine.approve(cid)
        engine.ingest(cid)

        knowledge = memory.recall()
        assert any("Repository" in p.name for p in knowledge.patterns)

    def test_full_pipeline_mistake(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="Never commit secrets to version control",
                suggested_type="mistake",
                confidence=0.9,
                risk_level="critical",
                dedupe_hash="pipe-mistake",
            )
        )

        engine.approve(cid)
        engine.ingest(cid)

        knowledge = memory.recall()
        assert any("secrets" in m.description for m in knowledge.mistakes)

    def test_full_pipeline_decision(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="ADR: Use SQLite for local persistence\n"
                "Decision: SQLite because zero deps and WAL mode",
                suggested_type="decision",
                confidence=0.9,
                risk_level="medium",
                dedupe_hash="pipe-decision",
            )
        )

        engine.approve(cid)
        engine.ingest(cid)

        knowledge = memory.recall()
        assert any("SQLite" in d.title for d in knowledge.decisions)

    def test_ingest_increments_version(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="Run tests before commit",
                suggested_type="convention",
                confidence=0.9,
                risk_level="low",
                dedupe_hash="pipe-version",
                state="approved",
            )
        )

        engine.ingest(cid)
        candidate = engine.get_candidate(cid)
        assert candidate.ingest_version == 1

        # Cannot re-ingest an already ingested candidate
        with pytest.raises(RuntimeError, match="must be approved"):
            engine.ingest(cid)

    def test_traceability_reviews_persisted(self, engines) -> None:
        engine, memory = engines
        store = engine.get_store()
        assert store is not None

        cid = store.insert_candidate(
            LearningCandidate(
                content="Use type hints everywhere",
                suggested_type="convention",
                confidence=0.9,
                risk_level="low",
                dedupe_hash="pipe-trace",
            )
        )

        engine.approve(cid, reviewer="human", reason="Looks correct")
        engine.ingest(cid)

        reviews = engine.get_reviews(cid)
        assert len(reviews) >= 2
        assert reviews[0]["decision"] == "approve"
        assert reviews[0]["reviewer"] == "human"
        assert reviews[1]["decision"] == "ingested"
        assert reviews[1]["reviewer"] == "engine"
