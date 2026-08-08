"""ContextBudget and ContextSelector — retrieve, rank, filter, select within token limits."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aios.knowledge.chunking import token_estimate
from aios.retrieval.retrievers import ScoredResult

_DEFAULT_BUDGETS: dict[str, int] = {
    "planner": 3000,
    "research": 5000,
    "reviewer": 2000,
}
_FALLBACK_DEFAULT = 3000

_SOURCE_BOOST: dict[str, float] = {
    "project_dna": 0.12,
    "code": 0.10,
    "adr": 0.08,
    "documentation": 0.05,
    "research": 0.06,
    "skill": 0.07,
    "memory": 0.04,
}


class ContextBudget:
    def __init__(self, overrides: dict[str, int] | None = None) -> None:
        self._budgets = dict(_DEFAULT_BUDGETS)
        if overrides:
            self._budgets.update(overrides)

    def for_agent(self, agent: str) -> int:
        return self._budgets.get(agent, _FALLBACK_DEFAULT)


@dataclass
class SelectionResult:
    chunks: list[ScoredResult] = field(default_factory=list)
    prompt_context: str = ""
    selected_count: int = 0
    chunks_retrieved: int = 0
    chunks_selected: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    compression_ratio: float = 0.0
    retrieval_latency_ms: float = 0.0


class ContextSelector:
    def __init__(
        self,
        retriever,
        budget: ContextBudget | None = None,
        fallback_retriever=None,
    ) -> None:
        self._retriever = retriever
        self._budget = budget or ContextBudget()
        self._fallback = fallback_retriever

    def select(self, query: str, *, agent: str, k: int = 20) -> SelectionResult:
        t0 = time.monotonic()

        token_limit = self._budget.for_agent(agent)

        candidates = self._retriever.retrieve(query, k=k)
        if not candidates and self._fallback is not None:
            candidates = self._fallback.retrieve(query, k=k)

        tokens_before = sum(r.result.token_estimate for r in candidates)
        chunks_retrieved = len(candidates)

        ranked = self._rank(candidates)
        diverse = self._dedupe(ranked)

        selected, tokens_after = self._greedy_select(diverse, token_limit)

        compression = 0.0
        if tokens_before > 0 and tokens_after > 0:
            compression = 1.0 - (tokens_after / tokens_before)

        prompt = self._build_prompt_context(selected)

        latency = (time.monotonic() - t0) * 1000

        return SelectionResult(
            chunks=selected,
            prompt_context=prompt,
            selected_count=len(selected),
            chunks_retrieved=chunks_retrieved,
            chunks_selected=len(selected),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            compression_ratio=compression,
            retrieval_latency_ms=latency,
        )

    @staticmethod
    def _rank(scored: list[ScoredResult]) -> list[ScoredResult]:
        for s in scored:
            boost = _SOURCE_BOOST.get(s.result.source_type, 0.0)
            s.score = min(1.0, s.score + boost)
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    @staticmethod
    def _dedupe(scored: list[ScoredResult]) -> list[ScoredResult]:
        seen_sources: set[str] = set()
        result: list[ScoredResult] = []
        for s in scored:
            key = s.result.source_id
            if key not in seen_sources:
                seen_sources.add(key)
                result.append(s)
        return result

    @staticmethod
    def _greedy_select(
        scored: list[ScoredResult], token_limit: int
    ) -> tuple[list[ScoredResult], int]:
        selected: list[ScoredResult] = []
        used = 0
        for s in scored:
            est = s.result.token_estimate
            if used + est <= token_limit:
                selected.append(s)
                used += est
            elif est > token_limit and used == 0:
                truncated = _truncate_to_tokens(s.result.content, token_limit)
                s.result.content = truncated
                s.result.token_estimate = token_estimate(truncated)
                selected.append(s)
                used = token_limit
                break
            else:
                _build_justification(s, dropped=True)
        for s in selected:
            _build_justification(s)
        return selected, used

    @staticmethod
    def _build_prompt_context(chunks: list[ScoredResult]) -> str:
        if not chunks:
            return ""
        lines = ["[Knowledge]"]
        for i, c in enumerate(chunks, 1):
            source = f"{c.result.source_type}/{c.result.source_path}"
            lines.append(f"[{i}] source={source} (score={c.score:.2f}) [pos={c.result.position}]")
            lines.append(c.result.content)
            lines.append("")
        return "\n".join(lines)


def _build_justification(s: ScoredResult, *, dropped: bool = False) -> None:
    prefix = "dropped" if dropped else "selected"
    source = f"{s.result.source_type}/{s.result.source_path}"
    s.justification = (
        f"{prefix}: score={s.score:.3f}; source={source}; tokens={s.result.token_estimate}"
    )


def _truncate_to_tokens(content: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    words = content.split()
    if len(words) <= max_tokens:
        return content
    return " ".join(words[:max_tokens])
