"""Mutation-killing tests for learning extractor, knowledge engine, and misc functions.

Targets extract_from_quality_event (59 killable), extract_from_agent_failure
(35 killable, zero prior tests), and helper functions.
"""

from __future__ import annotations

import pytest

from aios.learning.extractor import (
    _MEDIUM_RISK_CONFIDENCE_THRESHOLD,
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


# ===========================================================================
# Helper functions — STRING_MUTATION, CONSTANT_REPLACEMENT
# ===========================================================================


class TestDedupeHash:
    def test_basic_hash(self):
        h = dedupe_hash("hello")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_stripped(self):
        assert dedupe_hash("  hello  ") == dedupe_hash("hello")

    def test_deterministic(self):
        assert dedupe_hash("test") == dedupe_hash("test")

    def test_different_inputs(self):
        assert dedupe_hash("a") != dedupe_hash("b")


class TestMapSeverityToRisk:
    def test_critical(self):
        assert map_severity_to_risk("critical") == "critical"

    def test_high(self):
        assert map_severity_to_risk("high") == "high"

    def test_medium(self):
        assert map_severity_to_risk("medium") == "medium"

    def test_low(self):
        assert map_severity_to_risk("low") == "low"

    def test_unknown_defaults_low(self):
        assert map_severity_to_risk("unknown") == "low"

    def test_empty_defaults_low(self):
        assert map_severity_to_risk("") == "low"


class TestConfidenceFromGateSeverity:
    def test_critical(self):
        assert confidence_from_gate_severity("critical") == 0.9

    def test_high(self):
        assert confidence_from_gate_severity("high") == 0.7

    def test_medium(self):
        assert confidence_from_gate_severity("medium") == 0.5

    def test_low(self):
        assert confidence_from_gate_severity("low") == 0.3

    def test_unknown_defaults_03(self):
        assert confidence_from_gate_severity("unknown") == 0.3

    def test_empty_defaults_03(self):
        assert confidence_from_gate_severity("") == 0.3


class TestMapGateFindingToType:
    def test_critical_is_mistake(self):
        assert map_gate_finding_to_type("critical") == "mistake"

    def test_high_is_mistake(self):
        assert map_gate_finding_to_type("high") == "mistake"

    def test_medium_is_pattern(self):
        assert map_gate_finding_to_type("medium") == "pattern"

    def test_low_is_pattern(self):
        assert map_gate_finding_to_type("low") == "pattern"

    def test_unknown_is_pattern(self):
        assert map_gate_finding_to_type("unknown") == "pattern"


class TestMapCandidateKindToType:
    def test_convention(self):
        assert map_candidate_kind_to_type("convention") == "convention"

    def test_decision(self):
        assert map_candidate_kind_to_type("decision") == "decision"

    def test_pattern(self):
        assert map_candidate_kind_to_type("pattern") == "pattern"

    def test_mistake(self):
        assert map_candidate_kind_to_type("mistake") == "mistake"

    def test_dependency_note(self):
        assert map_candidate_kind_to_type("dependency-note") == "architecture_note"

    def test_unknown_defaults_pattern(self):
        assert map_candidate_kind_to_type("unknown") == "pattern"

    def test_empty_defaults_pattern(self):
        assert map_candidate_kind_to_type("") == "pattern"


# ===========================================================================
# extract_from_quality_event — STRING_MUTATION, ARG_REMOVAL
# ===========================================================================


class TestExtractFromQualityEvent:
    def test_empty_payload(self):
        assert extract_from_quality_event({}) == []

    def test_no_findings(self):
        assert extract_from_quality_event({"findings": []}) == []

    def test_findings_dict_not_list(self):
        """findings as dict (findings_counts) should produce empty list."""
        assert extract_from_quality_event({"findings": {"critical": 1}}) == []

    def test_single_finding(self):
        payload = {
            "findings": [{"severity": "high", "detail": "lint error", "id": "f1"}],
            "correlation_id": "corr-1",
            "source_event": "quality.gate_failed",
        }
        obs = extract_from_quality_event(payload)
        assert len(obs) == 1
        o = obs[0]
        assert o.content == "lint error"
        assert o.suggested_type == "mistake"
        assert o.confidence == 0.7
        assert o.risk_level == "high"
        assert o.source_execution_id == "corr-1"
        assert o.source_event == "quality.gate_failed"

    def test_finding_without_detail_uses_title(self):
        payload = {
            "findings": [{"severity": "low", "title": "style issue"}],
        }
        obs = extract_from_quality_event(payload)
        assert len(obs) == 1
        assert obs[0].content == "style issue"

    def test_finding_without_content_skipped(self):
        payload = {
            "findings": [{"severity": "low"}],
        }
        assert extract_from_quality_event(payload) == []

    def test_multiple_findings(self):
        payload = {
            "findings": [
                {"severity": "critical", "detail": "a"},
                {"severity": "low", "detail": "b"},
            ],
        }
        obs = extract_from_quality_event(payload)
        assert len(obs) == 2
        assert obs[0].suggested_type == "mistake"
        assert obs[1].suggested_type == "pattern"

    def test_confidence_values(self):
        for sev, conf in [("critical", 0.9), ("high", 0.7), ("medium", 0.5), ("low", 0.3)]:
            payload = {"findings": [{"severity": sev, "detail": "x"}]}
            obs = extract_from_quality_event(payload)
            assert obs[0].confidence == conf

    def test_risk_levels(self):
        for sev, risk in [("critical", "critical"), ("high", "high"), ("medium", "medium"), ("low", "low")]:
            payload = {"findings": [{"severity": sev, "detail": "x"}]}
            obs = extract_from_quality_event(payload)
            assert obs[0].risk_level == risk

    def test_dedupe_hash(self):
        payload = {"findings": [{"severity": "low", "detail": "same text"}]}
        obs = extract_from_quality_event(payload)
        assert obs[0].dedupe_hash == dedupe_hash("same text")

    def test_evidence_refs(self):
        payload = {
            "findings": [{"severity": "high", "detail": "err", "id": "f42"}],
        }
        obs = extract_from_quality_event(payload)
        refs = obs[0].evidence_refs
        assert len(refs) == 1
        assert refs[0]["source_event"] == "quality.gate_failed"
        assert refs[0]["source_id"] == "f42"
        assert refs[0]["severity"] == "high"
        assert refs[0]["detail"] == "err"

    def test_correlation_id_propagated(self):
        payload = {
            "findings": [{"severity": "low", "detail": "x"}],
            "correlation_id": "test-corr",
        }
        obs = extract_from_quality_event(payload)
        assert obs[0].source_execution_id == "test-corr"

    def test_source_event_propagated(self):
        payload = {
            "findings": [{"severity": "low", "detail": "x"}],
            "source_event": "custom.event",
        }
        obs = extract_from_quality_event(payload)
        assert obs[0].source_event == "custom.event"

    def test_finding_none_detail(self):
        payload = {"findings": [{"severity": "low", "detail": None, "title": ""}]}
        assert extract_from_quality_event(payload) == []


# ===========================================================================
# extract_from_agent_failure — zero prior tests, 35 killable
# ===========================================================================


class TestExtractFromAgentFailure:
    def test_empty_payload(self):
        assert extract_from_agent_failure({}) == []

    def test_empty_errors(self):
        assert extract_from_agent_failure({"errors": []}) == []

    def test_single_error(self):
        payload = {"errors": ["OOM killed"]}
        obs = extract_from_agent_failure(payload)
        assert len(obs) == 1
        assert obs[0].content == "OOM killed"
        assert obs[0].suggested_type == "mistake"
        assert obs[0].risk_level == "high"
        assert obs[0].source_event == "agent.execution.failed"

    def test_multiple_errors(self):
        payload = {"errors": ["err1", "err2", "err3"]}
        obs = extract_from_agent_failure(payload)
        assert len(obs) == 3

    def test_string_error_coerced_to_list(self):
        payload = {"errors": "single string error"}
        obs = extract_from_agent_failure(payload)
        assert len(obs) == 1
        assert obs[0].content == "single string error"

    def test_empty_string_error_skipped(self):
        payload = {"errors": [""]}
        assert extract_from_agent_failure(payload) == []

    def test_default_confidence(self):
        payload = {"errors": ["err"]}
        obs = extract_from_agent_failure(payload)
        assert obs[0].confidence == 0.6

    def test_recurrence_increases_confidence(self):
        payload = {"errors": ["err"]}
        obs = extract_from_agent_failure(payload, recurrence_count=3)
        assert obs[0].confidence > 0.6

    def test_recurrence_threshold_default(self):
        payload = {"errors": ["err"]}
        obs1 = extract_from_agent_failure(payload, recurrence_count=1)
        obs2 = extract_from_agent_failure(payload, recurrence_count=3)
        assert obs1[0].confidence == 0.6
        assert obs2[0].confidence > 0.6

    def test_recurrence_confidence_cap(self):
        payload = {"errors": ["err"]}
        obs = extract_from_agent_failure(payload, recurrence_count=100)
        assert obs[0].confidence <= 0.9

    def test_dedupe_hash(self):
        payload = {"errors": ["test error"]}
        obs = extract_from_agent_failure(payload)
        assert obs[0].dedupe_hash == dedupe_hash("test error")

    def test_evidence_refs(self):
        payload = {"errors": ["some error"]}
        obs = extract_from_agent_failure(payload)
        refs = obs[0].evidence_refs
        assert len(refs) == 1
        assert refs[0]["source_event"] == "agent.execution.failed"
        assert refs[0]["severity"] == "high"
        assert refs[0]["detail"] == "some error"

    def test_correlation_id(self):
        payload = {"errors": ["e"], "correlation_id": "cid-1"}
        obs = extract_from_agent_failure(payload)
        assert obs[0].source_execution_id == "cid-1"

    def test_source_id_format(self):
        payload = {"errors": ["e1", "e2"]}
        obs = extract_from_agent_failure(payload)
        assert obs[0].source_id == "agent-error-1"
        assert obs[1].source_id == "agent-error-2"


# ===========================================================================
# extract_from_research_event
# ===========================================================================


class TestExtractFromResearchEvent:
    def test_empty_payload(self):
        assert extract_from_research_event({}) == []

    def test_empty_candidates(self):
        assert extract_from_research_event({"memory_candidates": []}) == []

    def test_single_candidate(self):
        payload = {
            "memory_candidates": [
                {"content": "use pytest", "kind": "convention", "confidence": 0.8, "reason": "best practice"},
            ],
            "correlation_id": "rc-1",
        }
        obs = extract_from_research_event(payload)
        assert len(obs) == 1
        assert obs[0].content == "use pytest"
        assert obs[0].suggested_type == "convention"
        assert obs[0].confidence == 0.8
        assert obs[0].source_event == "research.completed"

    def test_risk_level_threshold(self):
        # confidence < 0.7 -> medium risk
        payload = {"memory_candidates": [{"content": "a", "confidence": 0.5}]}
        obs = extract_from_research_event(payload)
        assert obs[0].risk_level == "medium"

        # confidence >= 0.7 -> low risk
        payload = {"memory_candidates": [{"content": "b", "confidence": 0.8}]}
        obs = extract_from_research_event(payload)
        assert obs[0].risk_level == "low"

    def test_candidate_kind_mapping(self):
        for kind, expected in [("convention", "convention"), ("decision", "decision"),
                                ("pattern", "pattern"), ("mistake", "mistake"),
                                ("dependency-note", "architecture_note")]:
            payload = {"memory_candidates": [{"content": "x", "kind": kind}]}
            obs = extract_from_research_event(payload)
            assert obs[0].suggested_type == expected

    def test_empty_content_skipped(self):
        payload = {"memory_candidates": [{"content": "", "kind": "pattern"}]}
        assert extract_from_research_event(payload) == []

    def test_source_id_format(self):
        payload = {"memory_candidates": [{"content": "a"}, {"content": "b"}]}
        obs = extract_from_research_event(payload)
        assert obs[0].source_id == "research-candidate-1"
        assert obs[1].source_id == "research-candidate-2"

    def test_evidence_refs(self):
        payload = {
            "memory_candidates": [
                {"content": "x", "kind": "convention", "confidence": 0.9, "reason": "r"},
            ],
        }
        obs = extract_from_research_event(payload)
        refs = obs[0].evidence_refs
        assert refs[0]["source_event"] == "research.completed"
        assert refs[0]["source_id"] == "convention"
        assert refs[0]["confidence"] == 0.9
        assert refs[0]["detail"] == "r"


# ===========================================================================
# create_candidate_from_observation
# ===========================================================================


class TestCreateCandidateFromObservation:
    def _make_obs(self, **overrides):
        defaults = dict(
            source_execution_id="exec-1",
            source_event="test",
            source_id="s1",
            content="test content",
            suggested_type="pattern",
            evidence_refs=[{"source_event": "test", "source_id": "s1"}],
            confidence=0.8,
            risk_level="low",
            dedupe_hash="abc",
        )
        defaults.update(overrides)
        return ObservationRecord(**defaults)

    def test_creates_candidate(self):
        obs = self._make_obs()
        c = create_candidate_from_observation(obs)
        assert c is not None
        assert c.content == "test content"
        assert c.confidence == 0.8
        assert c.state == "scored"

    def test_no_evidence_returns_none(self):
        obs = self._make_obs(evidence_refs=[])
        assert create_candidate_from_observation(obs) is None

    def test_below_confidence_threshold(self):
        obs = self._make_obs(confidence=0.3)
        assert create_candidate_from_observation(obs, confidence_threshold=0.5) is None

    def test_meets_threshold(self):
        obs = self._make_obs(confidence=0.5)
        c = create_candidate_from_observation(obs, confidence_threshold=0.5)
        assert c is not None

    def test_min_evidence_not_met(self):
        obs = self._make_obs(evidence_refs=[{"a": 1}])
        c = create_candidate_from_observation(obs, min_evidence=2)
        assert c is None

    def test_default_params(self):
        obs = self._make_obs()
        c = create_candidate_from_observation(obs)
        assert c is not None
        assert c.project_id == obs.project_id

    def test_candidate_fields(self):
        obs = self._make_obs(
            suggested_type="mistake",
            risk_level="high",
            dedupe_hash="hash123",
        )
        c = create_candidate_from_observation(obs)
        assert c.suggested_type == "mistake"
        assert c.risk_level == "high"
        assert c.dedupe_hash == "hash123"


# ===========================================================================
# _MEDIUM_RISK_CONFIDENCE_THRESHOLD constant
# ===========================================================================


class TestConstants:
    def test_threshold_value(self):
        assert _MEDIUM_RISK_CONFIDENCE_THRESHOLD == 0.7
