"""Tests for learning models."""

from aios.learning.models import (
    IngestionRecord,
    LearningCandidate,
    ObservationRecord,
)


class TestObservationRecord:
    def test_defaults(self) -> None:
        obs = ObservationRecord()
        assert obs.id is None
        assert obs.source_execution_id == ""
        assert obs.source_event == ""
        assert obs.state == "draft"
        assert obs.confidence == 0.0
        assert obs.risk_level == "low"

    def test_to_dict(self) -> None:
        obs = ObservationRecord(
            id=1,
            source_execution_id="run-1",
            source_event="quality.gate_failed",
            source_id="F001",
            content="lint error: unused import",
            suggested_type="mistake",
            evidence_refs=[{"source_event": "quality.gate_failed", "source_id": "F001"}],
            confidence=0.9,
            risk_level="high",
            state="draft",
            project_id="/tmp/test",
        )
        d = obs.to_dict()
        assert d["id"] == 1
        assert d["state"] == "draft"
        assert d["risk_level"] == "high"
        assert len(d["evidence_refs"]) == 1


class TestLearningCandidate:
    def test_defaults(self) -> None:
        c = LearningCandidate()
        assert c.id is None
        assert c.state == "draft"
        assert c.suggested_type == "pattern"
        assert c.ingest_version == 0
        assert c.ingested_memory_id == ""

    def test_to_dict(self) -> None:
        c = LearningCandidate(
            id=10,
            observation_id=5,
            content="Use snake_case for Python",
            suggested_type="convention",
            confidence=0.85,
            risk_level="low",
            state="approved",
            ingest_version=1,
            ingested_memory_id="mem-42",
            project_id="/tmp/test",
        )
        d = c.to_dict()
        assert d["id"] == 10
        assert d["observation_id"] == 5
        assert d["state"] == "approved"
        assert d["ingest_version"] == 1


class TestIngestionRecord:
    def test_defaults(self) -> None:
        rec = IngestionRecord(candidate_id=1)
        assert rec.candidate_id == 1
        assert rec.advisor == ""
        assert rec.reviewer == ""
        assert rec.decision == ""


class TestStateTransitions:
    def test_valid_states(self) -> None:
        valid = {"draft", "scored", "approved", "rejected", "ingested"}
        c = LearningCandidate()
        for state in valid:
            c.state = state  # type: ignore[assignment]
            assert c.state == state
