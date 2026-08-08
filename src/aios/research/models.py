"""Research domain models — the Researcher contract.

ResearchTask in, ResearchResult out. Findings carry provenance:
every Finding references the ResearchSource ids that support its claim.

MemoryCandidate is advisory output only. It is never persisted here;
a future Memory admission mechanism decides whether a candidate becomes
project knowledge.
"""

from dataclasses import dataclass, field
from typing import Literal


class ResearchError(Exception):
    """Raised when the ResearchAgent produces a result that violates the contract."""


Scope = Literal["repo", "docs", "web", "mixed"]
SourceType = Literal["doc", "spec", "api", "blog", "adr", "code"]
Status = Literal["ok", "partial", "source_unavailable", "error"]
Priority = Literal["high", "medium", "low"]
CandidateKind = Literal["convention", "decision", "pattern", "mistake", "dependency-note"]

VALID_SCOPES = ("repo", "docs", "web", "mixed")
VALID_SOURCE_TYPES = ("doc", "spec", "api", "blog", "adr", "code")
VALID_STATUSES = ("ok", "partial", "source_unavailable", "error")
VALID_PRIORITIES = ("high", "medium", "low")
VALID_CANDIDATE_KINDS = ("convention", "decision", "pattern", "mistake", "dependency-note")


@dataclass
class ResearchTask:
    question: str
    scope: Scope = "mixed"
    constraints: dict = field(default_factory=dict)
    context_packet: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "scope": self.scope,
            "constraints": dict(self.constraints),
            "context_packet": dict(self.context_packet),
        }


@dataclass
class ResearchSource:
    id: str
    title: str
    url: str
    type: SourceType = "doc"
    retrieved_at: str = ""
    trust_score: float = 0.5
    snippet: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "type": self.type,
            "retrieved_at": self.retrieved_at,
            "trust_score": self.trust_score,
            "snippet": self.snippet,
            "tags": list(self.tags),
        }


@dataclass
class Finding:
    id: str
    claim: str
    evidence_source_ids: list[str]
    confidence: float = 0.5
    applies_to: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "claim": self.claim,
            "evidence_source_ids": list(self.evidence_source_ids),
            "confidence": self.confidence,
            "applies_to": self.applies_to,
            "tags": list(self.tags),
        }


@dataclass
class Recommendation:
    action: str
    rationale: str
    risk: str = "low"
    priority: Priority = "medium"
    source_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "rationale": self.rationale,
            "risk": self.risk,
            "priority": self.priority,
            "source_ids": list(self.source_ids),
        }


@dataclass
class MemoryCandidate:
    kind: CandidateKind
    content: str
    reason: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "content": self.content,
            "reason": self.reason,
            "confidence": self.confidence,
            "tags": list(self.tags),
        }


@dataclass
class ResearchResult:
    task: ResearchTask
    status: Status = "ok"
    summary_short: str = ""
    sources: list[ResearchSource] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    confidence_overall: float = 0.0
    recommendations: list[Recommendation] = field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "task": self.task.to_dict(),
            "status": self.status,
            "summary_short": self.summary_short,
            "sources": [s.to_dict() for s in self.sources],
            "findings": [f.to_dict() for f in self.findings],
            "confidence_overall": self.confidence_overall,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "memory_candidates": [m.to_dict() for m in self.memory_candidates],
            "error": self.error,
        }
