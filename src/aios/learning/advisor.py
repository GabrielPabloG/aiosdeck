"""Rules-based deterministic advisor for learning governance.

Implements the Advisor protocol. Deterministic, pluggable — a future
LLM-based advisor would conform to the same protocol.
"""

from __future__ import annotations

from aios.learning.contracts import ReviewDecision, default_review_logic
from aios.learning.models import LearningCandidate


class RulesAdvisor:
    """Deterministic advisor using confidence + risk + type rules."""

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self._confidence_threshold = confidence_threshold

    def review(self, candidate: LearningCandidate) -> ReviewDecision:
        return default_review_logic(candidate, self._confidence_threshold)

    @property
    def name(self) -> str:
        return "rules-advisor"

    @property
    def is_plug(self) -> bool:
        return True
