"""Tests for learning store (SQLite)."""

import tempfile
from pathlib import Path

import pytest

from aios.learning.models import LearningCandidate, ObservationRecord
from aios.learning.store import LearningStore


@pytest.fixture
def store() -> LearningStore:
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_learning.db"
        s = LearningStore(db_path, "/tmp/test-project")
        s.open()
        yield s
        s.close()


class TestObservationStorage:
    def test_insert_and_find_by_source(self, store: LearningStore) -> None:
        obs = ObservationRecord(
            source_execution_id="run-1",
            source_event="quality.gate_failed",
            source_id="F001",
            content="lint error",
            suggested_type="mistake",
            confidence=0.9,
            risk_level="high",
            dedupe_hash="abc123",
        )
        obs_id = store.insert_observation(obs)
        assert obs_id > 0

        found = store.find_observation_by_source("run-1", "F001")
        assert found is not None
        assert found.content == "lint error"
        assert found.confidence == 0.9

    def test_find_nonexistent(self, store: LearningStore) -> None:
        found = store.find_observation_by_source("no-run", "no-id")
        assert found is None

    def test_deduplicate_observations(self, store: LearningStore) -> None:
        obs1 = ObservationRecord(
            source_execution_id="run-1",
            source_event="quality.gate_failed",
            source_id="F001",
            content="lint error",
        )
        obs2 = ObservationRecord(
            source_execution_id="run-1",
            source_event="quality.gate_failed",
            source_id="F001",
            content="lint error duplicate",
        )
        store.insert_observation(obs1)
        store.insert_observation(obs2)
        found = store.find_observation_by_source("run-1", "F001")
        assert found is not None


class TestCandidateStorage:
    def test_insert_and_get(self, store: LearningStore) -> None:
        c = LearningCandidate(
            observation_id=1,
            content="Use snake_case",
            suggested_type="convention",
            confidence=0.85,
            risk_level="low",
            dedupe_hash="hash-snake",
        )
        cid = store.insert_candidate(c)
        assert cid > 0

        got = store.get_candidate(cid)
        assert got is not None
        assert got.content == "Use snake_case"
        assert got.state == "draft"

    def test_find_by_hash_draft(self, store: LearningStore) -> None:
        c = LearningCandidate(
            content="test pattern",
            suggested_type="pattern",
            dedupe_hash="hash-dup",
        )
        store.insert_candidate(c)
        found = store.find_candidate_by_hash("hash-dup")
        assert found is not None
        assert found.dedupe_hash == "hash-dup"

    def test_find_by_hash_excludes_rejected(self, store: LearningStore) -> None:
        c = LearningCandidate(
            content="rejected pattern",
            suggested_type="pattern",
            dedupe_hash="hash-rej",
            state="rejected",
        )
        store.insert_candidate(c)
        found = store.find_candidate_by_hash("hash-rej")
        assert found is None

        found_rej = store.find_candidate_by_hash("hash-rej", states=("rejected",))
        assert found_rej is not None

    def test_list_candidates_by_state(self, store: LearningStore) -> None:
        for i in range(3):
            c = LearningCandidate(
                content=f"candidate {i}",
                suggested_type="pattern",
                dedupe_hash=f"hash-{i}",
            )
            store.insert_candidate(c)

        all_candidates = store.list_candidates(limit=10)
        assert len(all_candidates) == 3

        store.update_candidate_state(all_candidates[0].id, "approved")  # type: ignore[arg-type]
        approved = store.list_candidates(state="approved")
        assert len(approved) == 1
        assert approved[0].state == "approved"

    def test_update_state(self, store: LearningStore) -> None:
        c = LearningCandidate(content="test", dedupe_hash="hash-upd")
        cid = store.insert_candidate(c)
        store.update_candidate_state(cid, "approved", ingest_version=1, ingested_memory_id="m-1")

        updated = store.get_candidate(cid)
        assert updated is not None
        assert updated.state == "approved"
        assert updated.ingest_version == 1
        assert updated.ingested_memory_id == "m-1"

    def test_count_by_hash(self, store: LearningStore) -> None:
        c = LearningCandidate(content="test", dedupe_hash="hash-count")
        store.insert_candidate(c)
        assert store.count_candidates_by_hash("hash-count") == 1
        assert store.count_candidates_by_hash("nonexistent") == 0


class TestReviewStorage:
    def test_insert_and_get_reviews(self, store: LearningStore) -> None:
        c = LearningCandidate(content="test", dedupe_hash="hash-rev")
        cid = store.insert_candidate(c)

        store.insert_review(
            candidate_id=cid,
            advisor="rules-advisor",
            recommendation="approve",
            justification="confidence high",
            reviewer="human",
            decision="approve",
            reason="manual approval",
        )
        reviews = store.get_reviews(cid)
        assert len(reviews) == 1
        assert reviews[0]["decision"] == "approve"
        assert reviews[0]["reviewer"] == "human"


class TestMaterializationStorage:
    def test_insert_materialization(self, store: LearningStore) -> None:
        mid = store.insert_materialization("md", "/tmp/export.md", 5)
        assert mid > 0
