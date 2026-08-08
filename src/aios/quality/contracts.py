"""Quality gate contracts — canonical types and vocabulary.

These dataclasses and enums are the public API of the quality pipeline.
The workflow engine and the CLI consume gate results exclusively through
these types; no gate ever returns loose text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class GateStatus(Enum):
    """Canonical gate outcome vocabulary."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class Severity(Enum):
    """Canonical severity vocabulary.

    Reviewer detectors emit ``info`` / ``warning`` / ``error``; those map to
    ``low`` / ``medium`` / ``high``. ``critical`` is reserved for policy
    escalation and is never produced by the reviewer mapper.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class GateInput:
    """Everything a gate may need to inspect a change."""

    project_path: Path | None = None
    files: list[str] = field(default_factory=list)
    test_report: dict[str, Any] | None = None
    review_report: dict[str, Any] | None = None
    environment: str = "dev"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateFinding:
    """A single structured finding produced by a gate."""

    id: str
    title: str
    detail: str = ""
    severity: Severity = Severity.MEDIUM
    category: str = ""
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity.value,
            "category": self.category,
            "evidence": self.evidence,
        }


@dataclass
class GateResult:
    """Structured gate outcome — never free text."""

    status: GateStatus
    reason: str = ""
    findings: list[GateFinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "findings": [finding.to_dict() for finding in self.findings],
            "metadata": self.metadata,
        }


@runtime_checkable
class QualityGate(Protocol):
    """Every quality gate implements this protocol."""

    name: str

    async def run(self, gate_input: GateInput) -> GateResult: ...

    def is_applicable(self, gate_input: GateInput) -> bool: ...


_SEVERITY_MAP: dict[str, Severity] = {
    "info": Severity.LOW,
    "warning": Severity.MEDIUM,
    "error": Severity.HIGH,
}


def severity_mapper(reviewer_severity: str) -> Severity:
    """Map a reviewer severity to the canonical vocabulary.

    Args:
        reviewer_severity: One of ``info``, ``warning``, ``error``
            (case-insensitive), as emitted by aios.agents.detectors.

    Returns:
        The canonical ``Severity``. Unknown input raises ``ValueError`` so a
        typo can never silently downgrade a finding.
    """
    try:
        return _SEVERITY_MAP[reviewer_severity.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown reviewer severity: {reviewer_severity}") from exc
