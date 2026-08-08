"""Tests for research schema validation and (de)serialization."""

from aios.research import (
    Finding,
    MemoryCandidate,
    Recommendation,
    ResearchResult,
    ResearchSource,
    ResearchTask,
)
from aios.research.schema import (
    research_result_from_dict,
    research_result_to_json,
    validate_research_result,
    validate_research_task,
)


def _result() -> ResearchResult:
    source = ResearchSource(
        id="s1",
        title="Source",
        url="https://example.com/1",
        type="doc",
        retrieved_at="2026-08-08T00:00:00Z",
        trust_score=0.8,
        snippet="Use X",
    )
    return ResearchResult(
        task=ResearchTask(question="auth flow", scope="web"),
        status="ok",
        summary_short="Collected 1 source(s).",
        sources=[source],
        findings=[Finding(id="F1", claim="Use X", evidence_source_ids=["s1"], confidence=0.8)],
        confidence_overall=0.8,
        recommendations=[Recommendation(action="Do Y", rationale="Because Z")],
        memory_candidates=[MemoryCandidate(kind="pattern", content="Use X", confidence=0.8)],
    )


def test_valid_result_passes():
    assert validate_research_result(_result()) == []


def test_task_validation():
    assert validate_research_task(ResearchTask(question="", scope="web"))
    assert validate_research_task(ResearchTask(question="ok", scope="invalid"))


def test_finding_with_unknown_source_fails():
    result = _result()
    result.findings[0].evidence_source_ids = ["does-not-exist"]
    errors = validate_research_result(result)
    assert any("unknown evidence source id" in e for e in errors)


def test_finding_without_evidence_fails():
    result = _result()
    result.findings[0].evidence_source_ids = []
    errors = validate_research_result(result)
    assert any("at least one evidence source" in e for e in errors)


def test_summary_too_long_fails():
    result = _result()
    result.summary_short = "x" * 141
    errors = validate_research_result(result)
    assert any("summary_short" in e for e in errors)


def test_duplicate_source_id_fails():
    result = _result()
    result.sources.append(
        ResearchSource(id="s1", title="dup", url="https://example.com/dup", type="doc")
    )
    errors = validate_research_result(result)
    assert any("duplicate source id" in e for e in errors)


def test_confidence_out_of_range_fails():
    result = _result()
    result.confidence_overall = 1.5
    result.findings[0].confidence = -0.1
    errors = validate_research_result(result)
    assert any("confidence_overall" in e for e in errors)
    assert any("finding F1" in e for e in errors)


def test_invalid_enum_fails():
    result = _result()
    result.status = "bogus"
    errors = validate_research_result(result)
    assert any("status" in e for e in errors)


def test_json_round_trip():
    original = _result()
    restored = research_result_from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert isinstance(research_result_to_json(original), str)
