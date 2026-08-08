"""Tests for learning advisor and review policy."""

import tempfile
from pathlib import Path

import pytest

from aios.learning.advisor import RulesAdvisor
from aios.learning.contracts import (
    ReviewPolicy,
    default_review_logic,
)
from aios.learning.engine import LearningEngine
from aios.learning.models import LearningCandidate


class TestRulesAdvisor:
    def test_approves_high_confidence_low_risk(self) -> None:
        advisor = RulesAdvisor(confidence_threshold=0.5)
        candidate = LearningCandidate(
            content="use consistent naming",
            suggested_type="convention",
            confidence=0.85,
            risk_level="low",
        )
        decision = advisor.review(candidate)
        assert decision.recommendation == "approve"
        assert decision.advisor == "rules-advisor"

    def test_needs_human_for_high_risk(self) -> None:
        advisor = RulesAdvisor(confidence_threshold=0.5)
        candidate = LearningCandidate(
            content="critical change needed",
            suggested_type="pattern",
            confidence=0.9,
            risk_level="high",
        )
        decision = advisor.review(candidate)
        assert decision.recommendation == "needs_human"

    def test_needs_human_for_decision_type(self) -> None:
        advisor = RulesAdvisor(confidence_threshold=0.5)
        candidate = LearningCandidate(
            content="ADR: use PostgreSQL",
            suggested_type="decision",
            confidence=0.95,
            risk_level="low",
        )
        decision = advisor.review(candidate)
        assert decision.recommendation == "needs_human"

    def test_rejects_below_threshold(self) -> None:
        advisor = RulesAdvisor(confidence_threshold=0.5)
        candidate = LearningCandidate(
            content="maybe useful pattern",
            suggested_type="pattern",
            confidence=0.3,
            risk_level="low",
        )
        decision = advisor.review(candidate)
        assert decision.recommendation == "reject"

    def test_justification_is_textual(self) -> None:
        advisor = RulesAdvisor(confidence_threshold=0.5)
        candidate = LearningCandidate(
            content="test",
            suggested_type="convention",
            confidence=0.8,
            risk_level="low",
        )
        decision = advisor.review(candidate)
        assert "approve" in decision.justification
        assert "confidence=" in decision.justification

    def test_name_property(self) -> None:
        advisor = RulesAdvisor()
        assert advisor.name == "rules-advisor"


class TestReviewPolicy:
    def test_default_policy_requires_human(self) -> None:
        policy = ReviewPolicy()
        candidate = LearningCandidate(
            suggested_type="pattern",
        )
        assert policy.requires_human(candidate) is True

    def test_auto_policy_allows_auto(self) -> None:
        policy = ReviewPolicy(policy={"pattern": "auto"})
        candidate = LearningCandidate(suggested_type="pattern")
        assert policy.requires_human(candidate) is False
        assert policy.auto_approve(candidate) is True

    def test_auto_policy_only_matches_specific_type(self) -> None:
        policy = ReviewPolicy(policy={"pattern": "auto"})
        convention = LearningCandidate(suggested_type="convention")
        assert policy.requires_human(convention) is True


class TestDefaultReviewLogic:
    def test_approve_convention_high_confidence(self) -> None:
        c = LearningCandidate(suggested_type="convention", confidence=0.9, risk_level="low")
        decision = default_review_logic(c, 0.5)
        assert decision.recommendation == "approve"

    def test_reject_low_confidence(self) -> None:
        c = LearningCandidate(suggested_type="pattern", confidence=0.2, risk_level="low")
        decision = default_review_logic(c, 0.5)
        assert decision.recommendation == "reject"

    def test_needs_human_critical_risk(self) -> None:
        c = LearningCandidate(suggested_type="pattern", confidence=0.9, risk_level="critical")
        decision = default_review_logic(c, 0.5)
        assert decision.recommendation == "needs_human"


class TestEngineApproveReject:
    @pytest.fixture
    def engine(self) -> LearningEngine:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "test_engine.db"
        eng = LearningEngine(
            project_path=Path("/tmp/test-proj"),
            db_path=str(db_path),
        )
        eng.initialize()
        yield eng
        eng.shutdown()

    def _create_candidate(self, engine: LearningEngine, **kwargs) -> int:
        store = engine.get_store()
        params = {
            "content": "test content",
            "suggested_type": "convention",
            "confidence": 0.85,
            "risk_level": "low",
            "dedupe_hash": "test-hash",
        }
        params.update(kwargs)
        c = LearningCandidate(**params)
        assert store is not None
        return store.insert_candidate(c)

    def test_approve_draft_candidate(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h1")
        review_id = engine.approve(cid)
        assert review_id > 0

        candidate = engine.get_candidate(cid)
        assert candidate is not None
        assert candidate.state == "approved"

        reviews = engine.get_reviews(cid)
        assert len(reviews) >= 1
        assert reviews[-1]["decision"] == "approve"

    def test_approve_scored_candidate(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h2", state="scored")
        review_id = engine.approve(cid)
        assert review_id > 0

        candidate = engine.get_candidate(cid)
        assert candidate.state == "approved"

    def test_reject_draft_candidate(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h3")
        review_id = engine.reject(cid, reason="not relevant")
        assert review_id > 0

        candidate = engine.get_candidate(cid)
        assert candidate.state == "rejected"

        reviews = engine.get_reviews(cid)
        assert reviews[-1]["decision"] == "reject"

    def test_reject_requires_reason(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h4")
        with pytest.raises(RuntimeError, match="Reason is required"):
            engine.reject(cid, reason="")

    def test_cannot_approve_already_approved(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h5")
        engine.approve(cid)
        with pytest.raises(RuntimeError, match="Cannot approve"):
            engine.approve(cid)

    def test_cannot_reject_already_approved(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h6")
        engine.approve(cid)
        with pytest.raises(RuntimeError, match="Cannot reject"):
            engine.reject(cid, reason="changed mind")

    def test_cannot_approve_rejected(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h7")
        engine.reject(cid, reason="bad")
        with pytest.raises(RuntimeError, match="Cannot approve"):
            engine.approve(cid)

    def test_nonexistent_candidate(self, engine: LearningEngine) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            engine.approve(9999)

    def test_advisor_recommendation(self, engine: LearningEngine) -> None:
        cid = self._create_candidate(engine, dedupe_hash="h8", confidence=0.9)
        rec = engine.get_advisor_recommendation(cid)
        assert rec is not None
        assert "recommendation" in rec
        assert "justification" in rec
        assert rec["advisor"] == "rules-advisor"
