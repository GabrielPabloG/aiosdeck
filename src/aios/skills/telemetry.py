"""Skill usage telemetry — records considered/selected/used lifecycle signals."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aios.skills.discovery import ScoredSkill
from aios.skills.retrieval import SkillContext

if TYPE_CHECKING:
    from aios.telemetry.engine import TelemetryEngine

logger = logging.getLogger("aios.skills.telemetry")


class SkillUsageRecorder:
    def __init__(
        self,
        telemetry: TelemetryEngine | None = None,
        execution_id: str = "",
        correlation_id: str = "",
    ) -> None:
        self._telemetry = telemetry
        self._execution_id = execution_id
        self._correlation_id = correlation_id

    def record_pipeline(
        self,
        skill_contexts: list[SkillContext],
        considered: list[ScoredSkill],
        *,
        intent: str,
        agent: str,
    ) -> None:
        if self._telemetry is None or not considered:
            return

        used_names = _used_names(skill_contexts)
        tokens_map = _tokens_map(skill_contexts)

        for s in considered:
            is_used = s.skill.name in used_names
            self._telemetry.record_skill_usage(
                {
                    "execution_id": self._execution_id,
                    "correlation_id": self._correlation_id,
                    "skill_name": s.skill.name,
                    "skill_version": s.skill.version,
                    "intent": intent,
                    "agent": agent,
                    "considered": 1,
                    "selected": 1,
                    "used": 1 if is_used else 0,
                    "relevance_score": s.score,
                    "tokens_contributed": tokens_map.get(s.skill.name, 0),
                    "downstream_success": None,
                }
            )


def _used_names(contexts: list[SkillContext]) -> set[str]:
    return {ctx.skill.skill.name for ctx in contexts}


def _tokens_map(contexts: list[SkillContext]) -> dict[str, int]:
    return {ctx.skill.skill.name: ctx.tokens_used for ctx in contexts}
