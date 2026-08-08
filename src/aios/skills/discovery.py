"""Skill Discovery — ranks skills by intent relevance."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aios.context.packet import ContextPacket
from aios.skills.metadata import SkillMetadata
from aios.skills.registry import SkillRegistry

logger = logging.getLogger("aios.skills.discovery")

_TRIGGER_WEIGHT = 0.50
_SCOPE_WEIGHT = 0.30
_PRIORITY_WEIGHT = 0.20
_DEFAULT_MIN_SCORE = 0.25
_DEFAULT_TOP_K = 5
_MAX_PRIORITY = 10


@dataclass
class ScoredSkill:
    skill: SkillMetadata
    score: float
    trigger_matches: list[str]
    scope_matches: list[str]
    priority_score: float


class SkillDiscoveryService:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        min_score: float = _DEFAULT_MIN_SCORE,
        top_k: int = _DEFAULT_TOP_K,
    ) -> None:
        self._registry = registry
        self._min_score = min_score
        self._top_k = top_k

    def discover(self, intent: str, context: ContextPacket | None = None) -> list[ScoredSkill]:
        skills = self._registry.skills
        if not skills:
            return []

        intent_lower = intent.lower().strip()
        if not intent_lower:
            return []

        context_text = _build_context_text(context)
        scored: list[ScoredSkill] = []

        for skill in skills:
            trigger_matches = _match_triggers(skill.triggers, intent_lower)
            scope_matches = _match_scope(skill.scope, context_text)

            trigger_score = _compute_trigger_score(trigger_matches, skill.triggers)
            scope_score = _compute_scope_score(scope_matches, skill.scope)
            priority_score = min(skill.priority, _MAX_PRIORITY) / _MAX_PRIORITY

            total = (
                _TRIGGER_WEIGHT * trigger_score
                + _SCOPE_WEIGHT * scope_score
                + _PRIORITY_WEIGHT * priority_score
            )

            if total < self._min_score:
                continue

            scored.append(
                ScoredSkill(
                    skill=skill,
                    score=round(total, 4),
                    trigger_matches=trigger_matches,
                    scope_matches=scope_matches,
                    priority_score=round(priority_score, 4),
                )
            )

        scored.sort(key=lambda s: (-s.score, s.skill.name))
        return scored[: self._top_k]


def _match_triggers(triggers: list[str], intent_lower: str) -> list[str]:
    if not triggers:
        return []
    return [t for t in triggers if t.lower() in intent_lower]


def _match_scope(scope: list[str], context_text: str) -> list[str]:
    if not scope or not context_text:
        return []
    return [s for s in scope if s.lower() in context_text]


def _compute_trigger_score(matched: list[str], declared: list[str]) -> float:
    if not declared:
        return 0.0
    return len(matched) / len(declared)


def _compute_scope_score(matched: list[str], declared: list[str]) -> float:
    if not declared:
        return 0.0  # no scope constraint → no signal (neither penalty nor boost)
    return len(matched) / len(declared)


def _build_context_text(context: ContextPacket | None) -> str:
    if context is None:
        return ""

    parts: list[str] = []

    lang = context.project.language
    if lang and lang != "unknown":
        parts.append(lang)

    name = context.project.name
    if name:
        parts.append(name)

    tools = context.tools
    for attr in ("linter", "formatter", "test_runner", "dependency_manager"):
        val = getattr(tools, attr, "")
        if val:
            parts.append(val)

    return " ".join(parts).lower()
