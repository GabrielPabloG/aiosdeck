"""Skill Retrieval — maps discovered skills to Knowledge Store chunks with budget."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from aios.knowledge.engine import KnowledgeEngine
from aios.retrieval.retrievers import ScoredResult
from aios.retrieval.selector import ContextBudget
from aios.skills.discovery import ScoredSkill

logger = logging.getLogger("aios.skills.retrieval")

_SKILL_SOURCE_TYPES = ["skill", "project_dna"]


@dataclass
class SkillContext:
    skill: ScoredSkill
    chunks: list[ScoredResult]
    prompt_section: str
    tokens_used: int
    relevance_score: float


class SkillRetrievalService:
    def __init__(
        self,
        knowledge: KnowledgeEngine,
        budget: ContextBudget | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._budget = budget or ContextBudget()

    def retrieve(
        self,
        scored: list[ScoredSkill],
        intent: str,
        *,
        agent: str,
        max_chunks_per_skill: int = 2,
    ) -> list[SkillContext]:
        if not scored:
            return []

        raw_results = self._knowledge.retrieve_raw(
            intent,
            limit=50,
            source_types=_SKILL_SOURCE_TYPES,
        )
        if not raw_results:
            return []

        scored_by_name = {s.skill.name: s for s in scored}
        chunks_by_skill: dict[str, list[ScoredResult]] = {}
        for r in raw_results:
            name = _extract_skill_name(r.result.source_path)
            if name and name in scored_by_name:
                chunks_by_skill.setdefault(name, []).append(r)

        if not chunks_by_skill:
            logger.debug("No skill chunks matched any discovered skills")
            return []

        token_limit = self._budget.for_agent(agent)
        context_order: list[tuple[str, float]] = sorted(
            [(name, scored_by_name[name].score) for name in chunks_by_skill],
            key=lambda x: x[1],
            reverse=True,
        )

        contexts: list[SkillContext] = []
        tokens_total = 0

        for name, relevance in context_order:
            if tokens_total >= token_limit:
                break

            chunks = sorted(chunks_by_skill[name], key=lambda c: c.score, reverse=True)
            selected_chunks: list[ScoredResult] = []
            skill_tokens = 0

            for ch in chunks[:max_chunks_per_skill]:
                est = ch.result.token_estimate
                if tokens_total + est > token_limit:
                    break
                selected_chunks.append(ch)
                tokens_total += est
                skill_tokens += est

            if selected_chunks:
                prompt = _format_skill_section(scored_by_name[name], selected_chunks)
                contexts.append(
                    SkillContext(
                        skill=scored_by_name[name],
                        chunks=selected_chunks,
                        prompt_section=prompt,
                        tokens_used=skill_tokens,
                        relevance_score=relevance,
                    )
                )

        return contexts


def _extract_skill_name(source_path: str) -> str | None:
    parts = Path(source_path).parts
    try:
        idx = parts.index("skills")
    except ValueError:
        return None
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return None


def _format_skill_section(scored: ScoredSkill, chunks: list[ScoredResult]) -> str:
    skill = scored.skill
    lines = ["## Relevant Skills"]
    trigger_info = (
        f" [triggers: {', '.join(scored.trigger_matches)}]" if scored.trigger_matches else ""
    )
    scope_info = f" [scope: {', '.join(scored.scope_matches)}]" if scored.scope_matches else ""
    lines.append(f"- **{skill.name}** (score={scored.score:.2f}){trigger_info}{scope_info}")
    if skill.description:
        lines.append(f"  {skill.description}")
    for ch in chunks:
        lines.append("")
        lines.append(ch.result.content)
    return "\n".join(lines)
