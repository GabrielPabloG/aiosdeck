"""Research schema — validation and (de)serialization for ResearchResult.

Validation enforces the contract guardrails:
- summary_short is bounded.
- Every Finding references existing source ids (traceability).
- ids are unique, confidence values are bounded, enums are respected.
"""

import json

from aios.research.models import (
    VALID_CANDIDATE_KINDS,
    VALID_PRIORITIES,
    VALID_SCOPES,
    VALID_SOURCE_TYPES,
    VALID_STATUSES,
    Finding,
    MemoryCandidate,
    Recommendation,
    ResearchResult,
    ResearchSource,
    ResearchTask,
)

SUMMARY_LIMIT = 140


def validate_research_task(task: ResearchTask) -> list[str]:
    errors: list[str] = []
    if not task.question.strip():
        errors.append("question is required")
    if task.scope not in VALID_SCOPES:
        errors.append(f"scope must be one of {', '.join(VALID_SCOPES)}")
    return errors


def validate_research_result(result: ResearchResult) -> list[str]:
    """Return a list of contract violations. Empty list means valid."""
    errors: list[str] = []
    errors.extend(validate_research_task(result.task))

    if result.status not in VALID_STATUSES:
        errors.append(f"status must be one of {', '.join(VALID_STATUSES)}")
    if len(result.summary_short) > SUMMARY_LIMIT:
        errors.append(f"summary_short exceeds {SUMMARY_LIMIT} characters")
    if not 0.0 <= result.confidence_overall <= 1.0:
        errors.append("confidence_overall must be between 0.0 and 1.0")

    errors.extend(_validate_sources(result.sources))
    errors.extend(_validate_findings(result.findings, result.sources))
    errors.extend(_validate_recommendations(result.recommendations, result.sources))
    errors.extend(_validate_memory_candidates(result.memory_candidates))
    return errors


def _validate_sources(sources: list[ResearchSource]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            errors.append(f"duplicate source id: {source.id}")
        seen.add(source.id)
        if not source.url.strip():
            errors.append(f"source {source.id}: url is required")
        if source.type not in VALID_SOURCE_TYPES:
            types = ", ".join(VALID_SOURCE_TYPES)
            errors.append(f"source {source.id}: type must be one of {types}")
        if not 0.0 <= source.trust_score <= 1.0:
            errors.append(f"source {source.id}: trust_score must be between 0.0 and 1.0")
    return errors


def _validate_findings(findings: list[Finding], sources: list[ResearchSource]) -> list[str]:
    errors: list[str] = []
    source_ids = {s.id for s in sources}
    seen: set[str] = set()
    for finding in findings:
        if finding.id in seen:
            errors.append(f"duplicate finding id: {finding.id}")
        seen.add(finding.id)
        if not finding.claim.strip():
            errors.append(f"finding {finding.id}: claim is required")
        if not finding.evidence_source_ids:
            errors.append(f"finding {finding.id}: requires at least one evidence source")
        for sid in finding.evidence_source_ids:
            if sid not in source_ids:
                errors.append(f"finding {finding.id}: unknown evidence source id: {sid}")
        if not 0.0 <= finding.confidence <= 1.0:
            errors.append(f"finding {finding.id}: confidence must be between 0.0 and 1.0")
    return errors


def _validate_recommendations(
    recommendations: list[Recommendation], sources: list[ResearchSource]
) -> list[str]:
    errors: list[str] = []
    source_ids = {s.id for s in sources}
    for rec in recommendations:
        if not rec.action.strip():
            errors.append("recommendation: action is required")
        if not rec.rationale.strip():
            errors.append(f"recommendation '{rec.action}': rationale is required")
        if rec.priority not in VALID_PRIORITIES:
            errors.append(
                f"recommendation '{rec.action}': priority must be one of "
                f"{', '.join(VALID_PRIORITIES)}"
            )
        for sid in rec.source_ids:
            if sid not in source_ids:
                errors.append(f"recommendation '{rec.action}': unknown source id: {sid}")
    return errors


def _validate_memory_candidates(candidates: list[MemoryCandidate]) -> list[str]:
    errors: list[str] = []
    for candidate in candidates:
        if candidate.kind not in VALID_CANDIDATE_KINDS:
            errors.append(
                f"memory candidate '{candidate.content}': kind must be one of "
                f"{', '.join(VALID_CANDIDATE_KINDS)}"
            )
        if not candidate.content.strip():
            errors.append("memory candidate: content is required")
        if not 0.0 <= candidate.confidence <= 1.0:
            errors.append(
                f"memory candidate '{candidate.content}': confidence must be between 0.0 and 1.0"
            )
    return errors


def research_result_to_json(result: ResearchResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def research_result_from_dict(data: dict) -> ResearchResult:
    task_data = data.get("task", {})
    task = ResearchTask(
        question=task_data.get("question", ""),
        scope=task_data.get("scope", "mixed"),
        constraints=task_data.get("constraints", {}),
        context_packet=task_data.get("context_packet", {}),
    )
    sources = [
        ResearchSource(
            id=s["id"],
            title=s.get("title", ""),
            url=s["url"],
            type=s.get("type", "doc"),
            retrieved_at=s.get("retrieved_at", ""),
            trust_score=s.get("trust_score", 0.5),
            snippet=s.get("snippet", ""),
            tags=s.get("tags", []),
        )
        for s in data.get("sources", [])
    ]
    findings = [
        Finding(
            id=f["id"],
            claim=f.get("claim", ""),
            evidence_source_ids=f.get("evidence_source_ids", []),
            confidence=f.get("confidence", 0.5),
            applies_to=f.get("applies_to", ""),
            tags=f.get("tags", []),
        )
        for f in data.get("findings", [])
    ]
    recommendations = [
        Recommendation(
            action=r.get("action", ""),
            rationale=r.get("rationale", ""),
            risk=r.get("risk", "low"),
            priority=r.get("priority", "medium"),
            source_ids=r.get("source_ids", []),
        )
        for r in data.get("recommendations", [])
    ]
    candidates = [
        MemoryCandidate(
            kind=c.get("kind", "convention"),
            content=c.get("content", ""),
            reason=c.get("reason", ""),
            confidence=c.get("confidence", 0.5),
            tags=c.get("tags", []),
        )
        for c in data.get("memory_candidates", [])
    ]
    return ResearchResult(
        task=task,
        status=data.get("status", "ok"),
        summary_short=data.get("summary_short", ""),
        sources=sources,
        findings=findings,
        confidence_overall=data.get("confidence_overall", 0.0),
        recommendations=recommendations,
        memory_candidates=candidates,
        error=data.get("error", ""),
    )
