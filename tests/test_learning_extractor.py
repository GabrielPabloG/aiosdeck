"""Tests for learning extractor and engine observe/extract."""

import tempfile
from pathlib import Path

import pytest

from aios.learning.engine import LearningEngine
from aios.learning.extractor import (
    confidence_from_gate_severity,
    create_candidate_from_observation,
    dedupe_hash,
    extract_from_agent_failure,
    extract_from_quality_event,
    extract_from_research_event,
    map_candidate_kind_to_type,
    map_gate_finding_to_type,
    map_severity_to_risk,
)
from aios.learning.models import ObservationRecord


class TestDedupe:
    def test_dedupe_hash_deterministic(self) -> None:
        h1 = dedupe_hash("hello world")
        h2 = dedupe_hash("hello world")
        assert h1 == h2

    def test_dedupe_hash_different_content(self) -> None:
        h1 = dedupe_hash("hello")
        h2 = dedupe_hash("world")
        assert h1 != h2

    def test_dedupe_hash_strips_whitespace(self) -> None:
        h1 = dedupe_hash("  hello  ")
        h2 = dedupe_hash("hello")
        assert h1 == h2


class TestSeverityMapping:
    def test_critical_to_high_confidence(self) -> None:
        assert confidence_from_gate_severity("critical") == 0.9

    def test_high_to_0_7(self) -> None:
        assert confidence_from_gate_severity("high") == 0.7

    def test_medium_to_0_5(self) -> None:
        assert confidence_from_gate_severity("medium") == 0.5

    def test_low_to_0_3(self) -> None:
        assert confidence_from_gate_severity("low") == 0.3

    def test_unknown_defaults_to_0_3(self) -> None:
        assert confidence_from_gate_severity("unknown") == 0.3

    def test_severity_to_risk_mapping(self) -> None:
        assert map_severity_to_risk("critical") == "critical"
        assert map_severity_to_risk("high") == "high"
        assert map_severity_to_risk("medium") == "medium"
        assert map_severity_to_risk("low") == "low"

    def test_gate_finding_to_mistake_for_critical(self) -> None:
        assert map_gate_finding_to_type("critical") == "mistake"
        assert map_gate_finding_to_type("high") == "mistake"
        assert map_gate_finding_to_type("medium") == "pattern"


class TestExtractFromQuality:
    def test_empty_findings(self) -> None:
        result = extract_from_quality_event({})
        assert result == []

    def test_single_finding(self) -> None:
        payload = {
            "correlation_id": "run-1",
            "findings": [
                {
                    "id": "F001",
                    "title": "unused import",
                    "detail": "Remove unused import os",
                    "severity": "high",
                }
            ],
        }
        result = extract_from_quality_event(payload)
        assert len(result) == 1
        obs = result[0]
        assert obs.source_event == "quality.gate_failed"
        assert obs.suggested_type == "mistake"
        assert obs.confidence == 0.7
        assert obs.risk_level == "high"

    def test_findings_dict_ignored(self) -> None:
        payload = {
            "findings": {"low": 2, "medium": 1},
        }
        result = extract_from_quality_event(payload)
        assert result == []


class TestExtractFromResearch:
    def test_empty_candidates(self) -> None:
        result = extract_from_research_event({"memory_candidates": []})
        assert result == []

    def test_single_candidate(self) -> None:
        payload = {
            "correlation_id": "run-2",
            "memory_candidates": [
                {
                    "kind": "convention",
                    "content": "Use snake_case for function names",
                    "confidence": 0.85,
                    "reason": "High-confidence finding",
                }
            ],
        }
        result = extract_from_research_event(payload)
        assert len(result) == 1
        obs = result[0]
        assert obs.source_event == "research.completed"
        assert obs.suggested_type == "convention"
        assert obs.confidence == 0.85

    def test_dependency_note_maps_to_architecture_note(self) -> None:
        assert map_candidate_kind_to_type("dependency-note") == "architecture_note"

    def test_empty_content_skipped(self) -> None:
        payload = {
            "memory_candidates": [
                {"kind": "pattern", "content": ""},
                {"kind": "pattern", "content": "valid"},
            ],
        }
        result = extract_from_research_event(payload)
        assert len(result) == 1


class TestExtractFromAgentFailure:
    def test_single_error(self) -> None:
        payload = {
            "correlation_id": "run-3",
            "errors": ["Subprocess failed with code 1"],
        }
        result = extract_from_agent_failure(payload)
        assert len(result) == 1
        obs = result[0]
        assert obs.source_event == "agent.execution.failed"
        assert obs.suggested_type == "mistake"
        assert obs.confidence == 0.6

    def test_recurrence_increases_confidence(self) -> None:
        payload = {"errors": ["repeated error"]}
        result = extract_from_agent_failure(payload, recurrence_count=3)
        assert result[0].confidence == 0.7  # 0.6 + 0.1 * (3 - 2)

    def test_recurrence_capped_at_0_9(self) -> None:
        payload = {"errors": ["very repeated error"]}
        result = extract_from_agent_failure(payload, recurrence_count=10)
        assert result[0].confidence == 0.9


class TestCreateCandidateFromObservation:
    def test_below_threshold_returns_none(self) -> None:
        obs = ObservationRecord(
            id=1,
            content="test",
            confidence=0.3,
            evidence_refs=[{"key": "val"}],
        )
        candidate = create_candidate_from_observation(obs, confidence_threshold=0.5)
        assert candidate is None

    def test_no_evidence_returns_none(self) -> None:
        obs = ObservationRecord(
            id=1,
            content="test",
            confidence=0.7,
            evidence_refs=[],
        )
        candidate = create_candidate_from_observation(obs, min_evidence=1)
        assert candidate is None

    def test_valid_observation_creates_candidate(self) -> None:
        obs = ObservationRecord(
            id=5,
            content="Use snake_case",
            suggested_type="convention",
            confidence=0.85,
            risk_level="low",
            evidence_refs=[{"source_event": "research.completed"}],
            dedupe_hash="abc123",
            project_id="/tmp/test",
        )
        candidate = create_candidate_from_observation(obs)
        assert candidate is not None
        assert candidate.state == "scored"
        assert candidate.content == "Use snake_case"
        assert candidate.confidence == 0.85
        assert candidate.observation_id == 5


class TestLearningEngineObserve:
    @pytest.fixture
    def engine(self) -> LearningEngine:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "test_learning.db"
        eng = LearningEngine(
            project_path=Path("/tmp/test-proj"),
            db_path=str(db_path),
        )
        eng.initialize()
        yield eng
        eng.shutdown()

    def test_observe_quality_event(self, engine: LearningEngine) -> None:
        payload = {
            "correlation_id": "run-1",
            "findings": [
                {
                    "id": "F001",
                    "title": "lint error",
                    "detail": "unused import",
                    "severity": "medium",
                }
            ],
        }
        ids = engine.observe("quality.gate_failed", payload)
        assert len(ids) == 1

    def test_observe_deduplicates_same_source(self, engine: LearningEngine) -> None:
        payload = {
            "findings": [
                {
                    "id": "F001",
                    "title": "lint error",
                    "detail": "unused import",
                    "severity": "medium",
                }
            ],
        }
        ids1 = engine.observe("quality.gate_failed", payload)
        ids2 = engine.observe("quality.gate_failed", payload)
        assert len(ids1) == 1
        assert len(ids2) == 0  # deduplicated

    def test_observe_when_disabled(self, engine: LearningEngine) -> None:
        engine.configure(enabled=False)
        ids = engine.observe("quality.gate_failed", {"findings": [{"id": "F", "detail": "x"}]})
        assert ids == []

    def test_observe_research_event(self, engine: LearningEngine) -> None:
        payload = {
            "correlation_id": "run-2",
            "memory_candidates": [
                {
                    "kind": "pattern",
                    "content": "DTOs should be immutable",
                    "confidence": 0.8,
                }
            ],
        }
        ids = engine.observe("research.completed", payload)
        assert len(ids) == 1


class TestLearningEngineExtract:
    @pytest.fixture
    def engine(self) -> LearningEngine:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "test_extract.db"
        eng = LearningEngine(
            project_path=Path("/tmp/test-proj"),
            db_path=str(db_path),
        )
        eng.initialize()
        yield eng
        eng.shutdown()

    def test_extract_from_observation(self, engine: LearningEngine) -> None:
        payload = {
            "findings": [
                {
                    "id": "F002",
                    "title": "security issue",
                    "detail": "hardcoded secret on line 42",
                    "severity": "critical",
                }
            ],
        }
        obs_ids = engine.observe("quality.gate_failed", payload)
        assert len(obs_ids) == 1

        candidate_ids = engine.extract(observation_id=obs_ids[0])
        assert len(candidate_ids) == 1

    def test_extract_deduplicates_by_hash(self, engine: LearningEngine) -> None:
        payload = {
            "findings": [
                {
                    "id": "F003",
                    "title": "dup test",
                    "detail": "same content again",
                    "severity": "high",
                }
            ],
        }
        obs_ids = engine.observe("quality.gate_failed", payload)
        candidate_ids1 = engine.extract(observation_id=obs_ids[0])

        # Same observation extracted again should not create duplicate
        candidate_ids2 = engine.extract(observation_id=obs_ids[0])
        assert len(candidate_ids1) == 1
        assert len(candidate_ids2) == 0

    def test_extract_below_threshold(self, engine: LearningEngine) -> None:
        engine.configure(confidence_threshold=0.8)
        payload = {
            "findings": [
                {
                    "id": "F004",
                    "title": "low confidence",
                    "detail": "minor style issue",
                    "severity": "low",
                }
            ],
        }
        obs_ids = engine.observe("quality.gate_failed", payload)
        assert len(obs_ids) == 1
        candidate_ids = engine.extract(observation_id=obs_ids[0])
        assert len(candidate_ids) == 0  # below threshold (0.3 < 0.8)
