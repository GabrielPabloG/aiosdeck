"""Learning governance contracts — types, scores, decisions, advisor protocol."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from aios.learning.models import CandidateType, LearningCandidate, RiskLevel


@dataclass
class ConfidenceScore:
    value: float = 0.0
    source: str = ""
    evidence_count: int = 0


@dataclass
class ReviewDecision:
    recommendation: str = "needs_human"
    justification: str = ""
    advisor: str = ""

    @property
    def approved(self) -> bool:
        return self.recommendation == "approve"

    @property
    def rejected(self) -> bool:
        return self.recommendation == "reject"

    @property
    def needs_human(self) -> bool:
        return self.recommendation == "needs_human"


@runtime_checkable
class Advisor(Protocol):
    def review(self, candidate: LearningCandidate) -> ReviewDecision: ...


@dataclass
class ReviewPolicy:
    policy: dict[str, str] = field(default_factory=dict)

    def requires_human(self, candidate: LearningCandidate) -> bool:
        """Check if the learning policy requires human approval for this candidate type.

        Default: everything requires human approval (fail-safe).
        A policy entry ``{tipo: "auto"}`` enables auto-approval.
        """
        mode = self.policy.get(candidate.suggested_type, "human")
        return mode != "auto"

    def auto_approve(self, candidate: LearningCandidate) -> bool:
        return not self.requires_human(candidate)

    @staticmethod
    def default_policy() -> dict[str, str]:
        return {}


_NEEDS_HUMAN_TYPES: set[CandidateType] = {"decision", "architecture_note", "dependency-note"}
_NEEDS_HUMAN_RISKS: set[RiskLevel] = {"high", "critical"}


def default_review_logic(
    candidate: LearningCandidate, confidence_threshold: float = 0.5
) -> ReviewDecision:
    """Deterministic review logic based on confidence, risk, and type.

    - needs_human: risk_level in (high, critical) OR type in
      (decision, architecture_note, dependency-note)
    - approve: confidence >= threshold AND risk in (low, medium) AND type in
      (convention, pattern, mistake)
    - reject: confidence < threshold
    """
    risk = candidate.risk_level
    kind = candidate.suggested_type
    confidence = candidate.confidence

    if risk in _NEEDS_HUMAN_RISKS or kind in _NEEDS_HUMAN_TYPES:
        return ReviewDecision(
            recommendation="needs_human",
            justification=(f"confidence={confidence:.2f}; risk={risk}; type={kind} → needs_human"),
            advisor="rules-advisor",
        )

    if confidence >= confidence_threshold:
        return ReviewDecision(
            recommendation="approve",
            justification=(f"confidence={confidence:.2f}; risk={risk}; type={kind} → approve"),
            advisor="rules-advisor",
        )

    return ReviewDecision(
        recommendation="reject",
        justification=(
            f"confidence={confidence:.2f}; risk={risk}; type={kind} → reject (below threshold)"
        ),
        advisor="rules-advisor",
    )
