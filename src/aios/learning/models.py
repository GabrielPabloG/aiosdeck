"""Learning data models — domain, not database."""

from dataclasses import dataclass, field
from typing import Literal

from aios.storage.errors import StoreError


class LearningStorageError(StoreError):
    """Domain error for learning storage failures."""


ObservationState = Literal["draft"]
CandidateState = Literal["draft", "scored", "approved", "rejected", "ingested"]
CandidateType = Literal[
    "convention", "decision", "pattern", "mistake", "dependency-note", "architecture_note"
]
RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass
class ObservationRecord:
    id: int | None = None
    source_execution_id: str = ""
    source_event: str = ""
    source_id: str = ""
    content: str = ""
    suggested_type: CandidateType = "pattern"
    evidence_refs: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    risk_level: RiskLevel = "low"
    dedupe_hash: str = ""
    state: ObservationState = "draft"
    project_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_execution_id": self.source_execution_id,
            "source_event": self.source_event,
            "source_id": self.source_id,
            "content": self.content,
            "suggested_type": self.suggested_type,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "dedupe_hash": self.dedupe_hash,
            "state": self.state,
            "project_id": self.project_id,
            "created_at": self.created_at,
        }


@dataclass
class LearningCandidate:
    id: int | None = None
    observation_id: int | None = None
    content: str = ""
    suggested_type: CandidateType = "pattern"
    confidence: float = 0.0
    risk_level: RiskLevel = "low"
    evidence_refs: list[dict] = field(default_factory=list)
    dedupe_hash: str = ""
    state: CandidateState = "draft"
    ingest_version: int = 0
    ingested_memory_id: str = ""
    project_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "content": self.content,
            "suggested_type": self.suggested_type,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "evidence_refs": self.evidence_refs,
            "dedupe_hash": self.dedupe_hash,
            "state": self.state,
            "ingest_version": self.ingest_version,
            "ingested_memory_id": self.ingested_memory_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class IngestionRecord:
    candidate_id: int
    advisor: str = ""
    recommendation: str = ""
    justification: str = ""
    reviewer: str = ""
    decision: str = ""
    reason: str = ""
    created_at: str = ""
