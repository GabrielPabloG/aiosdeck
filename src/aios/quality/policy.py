"""Quality gate policy — decision resolution for gate findings.

Decides whether a gate's findings block the workflow based on severity and
environment. Conservative by default: with no policy configured the most
restrictive behavior applies (fail-safe).

Rules:
- critical / high always block
- medium blocks in release, warns in dev
- low always warns
- no findings passes
- unknown environment → fail-safe block
- explicit overrides (matching gate + environment) lift a block, auditably
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aios.quality.contracts import Severity

_SEVERITY_RANK = {s.value: index for index, s in enumerate(Severity)}

DEFAULT_POLICY: dict[str, list[str]] = {
    "dev": ["critical", "high"],
    "release": ["critical", "high", "medium"],
}


class GateDecision(Enum):
    """Canonical decision vocabulary."""

    BLOCK = "block"
    PASS = "pass"
    WARN = "warn"


@dataclass
class GateOverride:
    """An explicit, auditable override that lifts a block for one gate/env."""

    gate: str
    environment: str
    reason: str


@dataclass
class DecisionResult:
    """The outcome of resolving a gate's findings against a policy."""

    decision: GateDecision
    gate: str
    environment: str
    findings: dict[str, int] = field(default_factory=dict)
    overridden: bool = False
    override_reason: str = ""
    reason: str = ""

    def blocks(self) -> bool:
        return self.decision is GateDecision.BLOCK and not self.overridden

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "gate": self.gate,
            "environment": self.environment,
            "findings": self.findings,
            "overridden": self.overridden,
            "override_reason": self.override_reason,
            "reason": self.reason,
        }


def resolve_decision(
    severities: list[Severity | str] | None = None,
    *,
    gate: str = "",
    environment: str = "dev",
    policy: dict[str, list[str]] | None = None,
    overrides: list[GateOverride | dict] | None = None,
) -> DecisionResult:
    """Resolve findings (as severities) against the policy for an environment.

    Args:
        severities: Canonical ``Severity`` values or their string labels.
        gate: Gate name, used for override matching and auditing.
        environment: Environment name (``dev``, ``release``, or custom).
        policy: Mapping ``{environment: [block_severities]}``. ``None`` or an
            empty mapping means the conservative default.
        overrides: List of ``GateOverride`` or dicts with
            ``gate`` / ``environment`` / ``reason`` keys.

    Returns:
        A ``DecisionResult`` whose ``blocks()`` reflects whether the
        workflow should stop.
    """
    normalized = _normalize(severities or [])
    findings = _counts(normalized)

    env_policy = (policy or DEFAULT_POLICY).get(environment)
    if env_policy is None:
        blocked = bool(normalized)
        decision = GateDecision.BLOCK if blocked else GateDecision.PASS
        reason = (
            f"no policy for environment {environment!r}; fail-safe block"
            if blocked
            else "no findings"
        )
    else:
        block_set = set(env_policy)
        if not normalized:
            decision = GateDecision.PASS
            reason = "no findings"
        elif any(sev in block_set for sev in normalized):
            decision = GateDecision.BLOCK
            blocking = [sev for sev, count in findings.items() if count and sev in block_set]
            reason = f"blocking severity: {', '.join(blocking)}"
        else:
            decision = GateDecision.WARN
            reason = "findings below block threshold for environment"

    result = DecisionResult(
        decision=decision,
        gate=gate,
        environment=environment,
        findings=findings,
        reason=reason,
    )

    override_reason = _find_override_reason(gate, environment, overrides)
    if override_reason and result.decision is GateDecision.BLOCK:
        result.decision = GateDecision.PASS
        result.overridden = True
        result.override_reason = override_reason
        result.reason = f"overridden: {override_reason}"
    return result


def _normalize(severities: list[Severity | str]) -> list[str]:
    values = []
    for sev in severities:
        value = sev.value if isinstance(sev, Severity) else str(sev).lower()
        if value in _SEVERITY_RANK:
            values.append(value)
    return values


def _counts(severities: list[str]) -> dict[str, int]:
    return {label: severities.count(label) for label in _SEVERITY_RANK}


def _find_override_reason(
    gate: str, environment: str, overrides: list[GateOverride | dict] | None
) -> str:
    for override in overrides or []:
        if isinstance(override, dict):
            if override.get("gate") == gate and override.get("environment") == environment:
                return override.get("reason", "")
        elif isinstance(override, GateOverride) and (
            override.gate == gate and override.environment == environment
        ):
            return override.reason
    return ""
