"""ResearchAgent — first-class researcher with a structured contract.

Input: ResearchTask. Output: ResearchResult with sources, findings,
confidence, recommendations, and advisory memory_candidates.

Pipeline:
1. Collect sources — repo/docs scopes use a deterministic local
   collector (filesystem_read only). Web/mixed scopes require an
   injected fetcher (Callable[[ResearchTask], list[ResearchSource]]);
   the core never performs network I/O itself.
2. Normalize and dedupe sources by URL.
3. Synthesize findings with provenance (evidence_source_ids) and an
   injected synthesizer, or a deterministic heuristic.
4. Report status explicitly: "ok", "partial" (web unavailable in a
   mixed scope), or "source_unavailable" (web-only scope without a
   fetcher). A missing fetcher never produces fabricated claims.

memory_candidates are advisory output only. This agent never persists
into the Memory Engine.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.agents.base import BaseAgent
from aios.agents.contracts import RUNTIME_ERROR, STATE_FAILED, AgentError, coerce_task
from aios.agents.models import AgentResult
from aios.research import (
    Finding,
    MemoryCandidate,
    Recommendation,
    ResearchError,
    ResearchResult,
    ResearchSource,
    ResearchTask,
)
from aios.research.models import VALID_CANDIDATE_KINDS, VALID_SCOPES
from aios.research.schema import research_result_to_json, validate_research_result

logger = logging.getLogger("aios.agent.research")

type Fetcher = Callable[[ResearchTask], list[ResearchSource]]
type Synthesizer = Callable[
    [ResearchTask, list[ResearchSource]],
    tuple[list[Finding], list[Recommendation], list[MemoryCandidate]],
]

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "site-packages",
    ".aios",
}
_TEXT_EXTENSIONS = (
    ".py",
    ".md",
    ".rst",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
    ".html",
    ".sh",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".java",
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "with",
    "do",
    "should",
    "we",
    "you",
    "your",
    "i",
    "me",
    "my",
}
_MAX_LOCAL_SOURCES = 10
_SNIPPET_CHARS = 160
_MIN_CANDIDATE_CONFIDENCE = 0.7
_MIN_KEYWORD_LENGTH = 3
_MAX_KEYWORDS = 5

_WEB_UNAVAILABLE_RECO = Recommendation(
    action="Configure a web source fetcher before requesting web research",
    rationale=(
        "Web collection is unavailable: no fetcher/provider is injected. "
        "This result contains no research claims about external sources."
    ),
    risk="high",
    priority="low",
)


class ResearchAgent(BaseAgent):
    name = "research"
    timeout = 60.0
    required_capabilities = ["filesystem_read"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        super().__init__()
        self._fetcher = fetcher
        self._synthesizer = synthesizer

    def _research(self, task: ResearchTask) -> ResearchResult:
        """Run the research pipeline for a single ResearchTask (internal domain API)."""
        sources = self._collect(task)
        sources = _dedupe_sources(sources)
        web_unavailable = _web_was_unavailable(task, self._fetcher)

        if not sources:
            return self._empty_result(task, web_unavailable)

        findings, recommendations, candidates = self._synthesize(task, sources, web_unavailable)
        confidence = _overall_confidence(sources)
        result = ResearchResult(
            task=task,
            status="partial" if web_unavailable else "ok",
            summary_short=_build_summary(sources, findings, confidence),
            sources=sources,
            findings=findings,
            confidence_overall=confidence,
            recommendations=recommendations,
            memory_candidates=candidates,
        )
        return self._validated(result)

    def execute(self, task, context) -> AgentResult:
        """Contract method — builds a ResearchTask from an AgentTask and runs it."""
        agent_task = coerce_task(task)
        scope = agent_task.params.get("scope", "mixed")
        if scope not in VALID_SCOPES:
            scope = "mixed"
        packet = agent_task.params.get("context_packet")
        if packet is None and context is not None:
            packet = getattr(context, "to_dict", lambda: {})()
        research_task = ResearchTask(
            question=agent_task.description,
            scope=scope,
            constraints=agent_task.params.get("constraints", {}),
            context_packet=packet or {},
        )
        try:
            result = self._research(research_task)
        except ResearchError as exc:
            return AgentResult(
                success=False,
                errors=[str(exc)],
                error=AgentError(code=RUNTIME_ERROR, message=str(exc)),
                error_code=RUNTIME_ERROR,
                status=STATE_FAILED,
                agent=self.name,
                task_id=agent_task.task_id,
                correlation_id=agent_task.correlation_id,
            )
        return AgentResult(
            success=result.status != "error",
            output=research_result_to_json(result),
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )

    def _collect(self, task: ResearchTask) -> list[ResearchSource]:
        sources: list[ResearchSource] = []
        if task.scope in ("repo", "docs", "mixed"):
            sources.extend(_collect_local(task))
        if task.scope in ("web", "mixed") and self._fetcher is not None:
            try:
                fetched = self._fetcher(task)
            except Exception as exc:  # noqa: BLE001 - a failing fetcher degrades gracefully
                logger.error("ResearchAgent fetcher failed: %s", exc)
                fetched = []
            sources.extend(fetched)
        return sources

    def _synthesize(
        self,
        task: ResearchTask,
        sources: list[ResearchSource],
        web_unavailable: bool,
    ) -> tuple[list[Finding], list[Recommendation], list[MemoryCandidate]]:
        if self._synthesizer is not None:
            findings, recommendations, candidates = self._synthesizer(task, sources)
        else:
            findings, recommendations, candidates = _heuristic_synthesize(sources)

        if web_unavailable:
            recommendations = [*recommendations, _WEB_UNAVAILABLE_RECO]
        return findings, recommendations, candidates

    @staticmethod
    def _empty_result(task: ResearchTask, web_unavailable: bool) -> ResearchResult:
        if web_unavailable:
            return ResearchResult(
                task=task,
                status="source_unavailable",
                summary_short=(
                    "Web collection unavailable: configure a fetcher/provider "
                    "to research external sources."
                ),
                sources=[],
                findings=[],
                confidence_overall=0.0,
                recommendations=[_WEB_UNAVAILABLE_RECO],
                memory_candidates=[],
            )
        return ResearchResult(
            task=task,
            status="ok",
            summary_short="No sources matched the research question.",
            sources=[],
            findings=[],
            confidence_overall=0.0,
        )

    @staticmethod
    def _validated(result: ResearchResult) -> ResearchResult:
        errors = validate_research_result(result)
        if errors:
            raise ResearchError("; ".join(errors))
        return result


def _web_was_unavailable(task: ResearchTask, fetcher: Fetcher | None) -> bool:
    return task.scope in ("web", "mixed") and fetcher is None


def _dedupe_sources(sources: list[ResearchSource]) -> list[ResearchSource]:
    seen: set[str] = set()
    unique: list[ResearchSource] = []
    for source in sources:
        key = source.url.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _overall_confidence(sources: list[ResearchSource]) -> float:
    if not sources:
        return 0.0
    return round(sum(s.trust_score for s in sources) / len(sources), 2)


def _build_summary(
    sources: list[ResearchSource], findings: list[Finding], confidence: float
) -> str:
    return (
        f"Collected {len(sources)} source(s), {len(findings)} finding(s), "
        f"confidence {confidence:.2f}."
    )


def _project_root(context_packet: dict) -> Path:
    project = context_packet.get("project", {}) or {}
    root = project.get("root") or context_packet.get("root")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _collect_local(task: ResearchTask) -> list[ResearchSource]:
    root = _project_root(task.context_packet)
    keywords = _keywords(task.question)
    if not keywords:
        return []

    now = datetime.now(UTC).isoformat()
    sources: list[ResearchSource] = []
    for path in _iter_text_files(root):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = f"{rel.as_posix()} {text}".lower()
        if not any(keyword in haystack for keyword in keywords):
            continue

        is_doc = any(part in ("docs", "doc", "documentation") for part in rel.parts)
        sources.append(
            ResearchSource(
                id=f"local-{len(sources) + 1}",
                title=rel.as_posix(),
                url=f"file://{rel.as_posix()}",
                type="doc" if is_doc else "code",
                retrieved_at=now,
                trust_score=0.7,
                snippet=_snippet(text, keywords),
                tags=["local"],
            )
        )
        if len(sources) >= _MAX_LOCAL_SOURCES:
            break
    return sources


def _iter_text_files(root: Path):
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in root.walk():
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.endswith(_TEXT_EXTENSIONS):
                yield dirpath / name


def _keywords(question: str) -> list[str]:
    return [
        word
        for word in question.lower().split()
        if len(word) >= _MIN_KEYWORD_LENGTH and word not in _STOPWORDS and word.isalpha()
    ][:_MAX_KEYWORDS]


def _snippet(text: str, keywords: list[str]) -> str:
    lowered = text.lower()
    positions = [lowered.find(kw) for kw in keywords if kw in lowered]
    if not positions:
        return text[:_SNIPPET_CHARS]
    start = max(0, min(positions) - _SNIPPET_CHARS // 2)
    return text[start : start + _SNIPPET_CHARS].strip()


def _heuristic_synthesize(
    sources: list[ResearchSource],
) -> tuple[list[Finding], list[Recommendation], list[MemoryCandidate]]:
    findings: list[Finding] = []
    for index, source in enumerate(sources, start=1):
        claim = source.snippet if source.snippet else source.title
        findings.append(
            Finding(
                id=f"F{index}",
                claim=claim[:200],
                evidence_source_ids=[source.id],
                confidence=source.trust_score,
                tags=list(source.tags),
            )
        )

    candidates: list[MemoryCandidate] = []
    for finding in findings:
        if finding.confidence < _MIN_CANDIDATE_CONFIDENCE:
            continue
        kind = _candidate_kind(finding.tags)
        if kind is None:
            continue
        candidates.append(
            MemoryCandidate(
                kind=kind,
                content=finding.claim,
                reason="High-confidence finding derived from a collected source",
                confidence=finding.confidence,
                tags=list(finding.tags),
            )
        )
    return findings, [], candidates


def _candidate_kind(tags: list[str]) -> str | None:
    for tag in tags:
        if tag in VALID_CANDIDATE_KINDS:
            return tag
    return None
