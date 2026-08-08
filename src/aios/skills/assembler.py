"""SkillAssembler — discovery + retrieval + safe fallback boundary."""

from __future__ import annotations

import logging

from aios.context.packet import ContextPacket
from aios.skills.discovery import ScoredSkill, SkillDiscoveryService
from aios.skills.retrieval import SkillContext, SkillRetrievalService
from aios.skills.telemetry import SkillUsageRecorder

logger = logging.getLogger("aios.skills.assembler")


class SkillAssembler:
    """Orchestrates discovery → retrieval → prompt contexts.

    All failures produce an empty list — never raise. The caller (agent)
    must fall back to the old static-skills path when [] is returned.
    """

    def __init__(
        self,
        discovery: SkillDiscoveryService | None = None,
        retrieval: SkillRetrievalService | None = None,
        recorder: SkillUsageRecorder | None = None,
    ) -> None:
        self._discovery = discovery
        self._retrieval = retrieval
        self._recorder = recorder

    def assemble(
        self,
        intent: str,
        context: ContextPacket,
        *,
        agent: str,
        task_id: str = "",
        correlation_id: str = "",
    ) -> list[SkillContext]:
        if self._discovery is None or self._retrieval is None:
            return []

        considered: list[ScoredSkill] = []
        try:
            considered = self._discovery.discover(intent, context)
        except Exception:
            logger.warning("Skill discovery failed; falling back to static skills", exc_info=True)
            return []

        if not considered:
            return []

        try:
            contexts = self._retrieval.retrieve(considered, intent, agent=agent)
        except Exception:
            logger.warning("Skill retrieval failed; falling back to static skills", exc_info=True)
            return []

        if self._recorder is not None:
            self._recorder.record_pipeline(contexts, considered, intent=intent, agent=agent)

        return contexts
