"""Learning extractor — confidence rules, dedupe, and type mapping."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from aios.learning.models import (
    CandidateType,
    LearningCandidate,
    ObservationRecord,
    RiskLevel,
)

type EventPayload = dict[str, Any]
type ExtractorFn = Callable[[EventPayload], list[ObservationRecord]]


def dedupe_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode()).hexdigest()


def map_severity_to_risk(severity: str) -> RiskLevel:
    mapping: dict[str, RiskLevel] = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    return mapping.get(severity, "low")


def confidence_from_gate_severity(severity: str) -> float:
    mapping = {
        "critical": 0.9,
        "high": 0.7,
        "medium": 0.5,
        "low": 0.3,
    }
    return mapping.get(severity, 0.3)


def map_gate_finding_to_type(severity: str) -> CandidateType:
    if severity in ("high", "critical"):
        return "mistake"
    return "pattern"


def extract_from_quality_event(payload: EventPayload) -> list[ObservationRecord]:
    findings_list: list[dict] = payload.get("findings", []) or []
    if isinstance(findings_list, dict):
        findings_list = []  # findings_counts dict, not actual findings

    observations: list[ObservationRecord] = []
    for finding in findings_list:
        severity = finding.get("severity", "low")
        content = finding.get("detail") or finding.get("title", "")
        if not content:
            continue
        obs = ObservationRecord(
            source_execution_id=payload.get("correlation_id", ""),
            source_event=payload.get("source_event", "quality.gate_failed"),
            source_id=finding.get("id", ""),
            content=content,
            suggested_type=map_gate_finding_to_type(severity),
            evidence_refs=[
                {
                    "source_event": "quality.gate_failed",
                    "source_id": finding.get("id", ""),
                    "severity": severity,
                    "detail": finding.get("detail", ""),
                }
            ],
            confidence=confidence_from_gate_severity(severity),
            risk_level=map_severity_to_risk(severity),
            dedupe_hash=dedupe_hash(content),
        )
        observations.append(obs)
    return observations


_MEDIUM_RISK_CONFIDENCE_THRESHOLD = 0.7


def extract_from_research_event(payload: EventPayload) -> list[ObservationRecord]:
    candidates: list[dict] = payload.get("memory_candidates", []) or []
    observations: list[ObservationRecord] = []
    for idx, mc in enumerate(candidates):
        content = mc.get("content", "")
        if not content:
            continue
        kind = mc.get("kind", "pattern")
        mapped_type = map_candidate_kind_to_type(kind)
        confidence = mc.get("confidence", 0.5)
        risk: RiskLevel = "medium" if confidence < _MEDIUM_RISK_CONFIDENCE_THRESHOLD else "low"

        observations.append(
            ObservationRecord(
                source_execution_id=payload.get("correlation_id", ""),
                source_event="research.completed",
                source_id=f"research-candidate-{idx + 1}",
                content=content,
                suggested_type=mapped_type,
                evidence_refs=[
                    {
                        "source_event": "research.completed",
                        "source_id": kind,
                        "confidence": confidence,
                        "detail": mc.get("reason", ""),
                    }
                ],
                confidence=confidence,
                risk_level=risk,
                dedupe_hash=dedupe_hash(content),
            )
        )

    return observations


def map_candidate_kind_to_type(kind: str) -> CandidateType:
    mapping: dict[str, CandidateType] = {
        "convention": "convention",
        "decision": "decision",
        "pattern": "pattern",
        "mistake": "mistake",
        "dependency-note": "architecture_note",
    }
    return mapping.get(kind, "pattern")


def extract_from_agent_failure(
    payload: EventPayload, recurrence_count: int = 1, recurrence_threshold: int = 2
) -> list[ObservationRecord]:
    errors = payload.get("errors", [])
    if isinstance(errors, str):
        errors = [errors]

    observations: list[ObservationRecord] = []
    for error in errors:
        if not error:
            continue
        content = str(error)
        confidence = 0.6
        if recurrence_count >= recurrence_threshold:
            confidence = min(0.9, 0.6 + 0.1 * (recurrence_count - 2))

        observations.append(
            ObservationRecord(
                source_execution_id=payload.get("correlation_id", ""),
                source_event="agent.execution.failed",
                source_id=f"agent-error-{len(observations) + 1}",
                content=content,
                suggested_type="mistake",
                evidence_refs=[
                    {
                        "source_event": "agent.execution.failed",
                        "source_id": "agent-execution",
                        "severity": "high",
                        "detail": content,
                    }
                ],
                confidence=confidence,
                risk_level="high",
                dedupe_hash=dedupe_hash(content),
            )
        )
    return observations


def create_candidate_from_observation(
    obs: ObservationRecord,
    confidence_threshold: float = 0.5,
    min_evidence: int = 1,
) -> LearningCandidate | None:
    if not obs.evidence_refs or len(obs.evidence_refs) < min_evidence:
        return None
    if obs.confidence < confidence_threshold:
        return None

    return LearningCandidate(
        observation_id=obs.id,
        content=obs.content,
        suggested_type=obs.suggested_type,
        confidence=obs.confidence,
        risk_level=obs.risk_level,
        evidence_refs=obs.evidence_refs,
        dedupe_hash=obs.dedupe_hash,
        state="scored",
        project_id=obs.project_id,
    )
