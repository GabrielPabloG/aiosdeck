"""Tests for ResearchAgent — first-class researcher contract."""

import json

import pytest

from aios.agents.models import AgentResult
from aios.agents.research import ResearchAgent
from aios.context.packet import ContextPacket
from aios.core.task import Task
from aios.research import (
    Finding,
    MemoryCandidate,
    ResearchError,
    ResearchResult,
    ResearchSource,
    ResearchTask,
)
from aios.research.schema import validate_research_result


def _source(
    sid: str, url: str, trust: float = 0.8, tags: list[str] | None = None
) -> ResearchSource:
    return ResearchSource(
        id=sid,
        title=f"Title {sid}",
        url=url,
        type="doc",
        retrieved_at="2026-08-08T00:00:00Z",
        trust_score=trust,
        snippet="Use X for Y",
        tags=tags or [],
    )


def _task(question: str = "auth flow", scope: str = "web", **kwargs) -> ResearchTask:
    return ResearchTask(question=question, scope=scope, **kwargs)


def test_research_agent_capabilities():
    assert "filesystem_read" in ResearchAgent.required_capabilities
    assert "internet" not in ResearchAgent.required_capabilities
    assert "shell" not in ResearchAgent.required_capabilities


def test_happy_path_fetcher_traceability():
    def fetcher(task):
        return [_source("s1", "https://example.com/1"), _source("s2", "https://example.com/2")]

    result = ResearchAgent(fetcher=fetcher).research(_task())
    assert isinstance(result, ResearchResult)
    assert result.status == "ok"
    source_ids = {s.id for s in result.sources}
    assert result.findings
    for finding in result.findings:
        assert finding.evidence_source_ids
        assert set(finding.evidence_source_ids) <= source_ids
    assert validate_research_result(result) == []


def test_web_without_fetcher_source_unavailable():
    result = ResearchAgent().research(_task(scope="web"))
    assert result.status == "source_unavailable"
    assert result.sources == []
    assert result.findings == []
    assert result.confidence_overall == 0.0
    assert result.memory_candidates == []
    assert validate_research_result(result) == []
    note = " ".join(r.action + " " + r.rationale for r in result.recommendations).lower()
    assert "unavailable" in note
    assert "no research claims" in note


def test_mixed_without_fetcher_partial(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate():\n    return True\n", encoding="utf-8")
    task = _task(scope="mixed", context_packet={"project": {"root": str(repo)}})

    result = ResearchAgent().research(task)
    assert result.status == "partial"
    assert result.sources
    assert all(s.url.startswith("file://") for s in result.sources)
    assert result.findings
    note = " ".join(r.action + " " + r.rationale for r in result.recommendations).lower()
    assert "unavailable" in note
    assert validate_research_result(result) == []


def test_repo_scope_local_collection(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "health.py").write_text("def health_check():\n    return True\n", encoding="utf-8")
    task = _task(
        question="health check",
        scope="repo",
        context_packet={"project": {"root": str(repo)}},
    )

    result = ResearchAgent().research(task)
    assert result.status == "ok"
    assert result.sources
    assert result.sources[0].type == "code"
    assert result.sources[0].url.startswith("file://")
    assert result.findings
    assert validate_research_result(result) == []


def test_docs_scope_collects_docs_type(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "guide.md").write_text("Auth flow explained in the guide.\n", encoding="utf-8")
    task = _task(
        question="auth flow",
        scope="docs",
        context_packet={"project": {"root": str(repo)}},
    )

    result = ResearchAgent().research(task)
    assert result.status == "ok"
    assert result.sources
    assert all(s.type == "doc" for s in result.sources)


def test_dedupe_sources_by_url():
    def fetcher(task):
        return [
            _source("s1", "https://example.com/a"),
            _source("s2", "https://example.com/a"),
            _source("s3", "https://example.com/b"),
        ]

    result = ResearchAgent(fetcher=fetcher).research(_task())
    unique = {s.url for s in result.sources}
    assert len(result.sources) == len(unique)
    assert unique == {"https://example.com/a", "https://example.com/b"}


def test_memory_candidates_consistent_via_synthesizer():
    def synthesizer(task, sources):
        findings = [
            Finding(
                id="F1",
                claim="Use X for Y",
                evidence_source_ids=[sources[0].id],
                confidence=0.9,
            )
        ]
        candidates = [
            MemoryCandidate(kind="pattern", content="Use X for Y", confidence=0.9, tags=["pattern"])
        ]
        return findings, [], candidates

    def fetcher(task):
        return [_source("s1", "https://example.com/1", trust=0.9, tags=["pattern"])]

    result = ResearchAgent(fetcher=fetcher, synthesizer=synthesizer).research(_task())
    assert len(result.memory_candidates) == 1
    candidate = result.memory_candidates[0]
    assert candidate.kind == "pattern"
    assert candidate.content
    assert 0.0 <= candidate.confidence <= 1.0
    assert validate_research_result(result) == []


def test_heuristic_memory_candidates_from_tagged_sources():
    def fetcher(task):
        return [_source("s1", "https://example.com/1", trust=0.9, tags=["convention"])]

    result = ResearchAgent(fetcher=fetcher).research(_task())
    kinds = [c.kind for c in result.memory_candidates]
    assert "convention" in kinds


def test_invalid_synthesis_raises_research_error():
    def synthesizer(task, sources):
        return [Finding(id="F1", claim="x", evidence_source_ids=["missing-source"])], [], []

    def fetcher(task):
        return [_source("s1", "https://example.com/1")]

    agent = ResearchAgent(fetcher=fetcher, synthesizer=synthesizer)
    with pytest.raises(ResearchError):
        agent.research(_task())


def test_execute_adapter_returns_agent_result(tmp_path):
    ctx = ContextPacket()
    ctx.project.root = str(tmp_path)
    (tmp_path / "config.txt").write_text("auth flow configuration\n", encoding="utf-8")

    agent = ResearchAgent()
    result = agent.execute(Task(description="auth flow"), ctx)
    assert isinstance(result, AgentResult)
    assert result.success is True
    data = json.loads(result.output)
    assert "sources" in data
    assert "findings" in data
    assert "status" in data
