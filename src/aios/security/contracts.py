"""Security intent contracts — canonical types for intent and effective permissions.

These dataclasses are the public vocabulary of the security layer:

- ``IntentPolicy`` — the explicit action set (with an explicit deny set) a
  run is allowed to perform.
- ``EffectivePermissions`` — the resolved intersection of intent and
  capability grants, serialized in deterministic (sorted) order.
- ``SecurityDecision`` — the auditable verdict for a single action.

``AgentCapabilities`` is imported from ``aios.agents.contracts`` and reused —
it is never recreated here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aios.agents.contracts import AgentCapabilities  # noqa: F401 - re-exported for callers

SOURCE_DEFAULT = "default"


@dataclass(frozen=True)
class IntentPolicy:
    """Explicit action vocabulary for a run.

    ``actions`` is the set of granular actions the intent requests; ``deny``
    is the set of granular actions explicitly removed from the run. An action
    absent from ``actions`` — or present in ``deny`` — is denied.
    """

    actions: frozenset[str] = frozenset()
    deny: frozenset[str] = frozenset()
    name: str = ""
    source: str = SOURCE_DEFAULT

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "source": self.source,
            "actions": sorted(self.actions),
            "deny": sorted(self.deny),
        }


@dataclass(frozen=True)
class EffectivePermissions:
    """Resolved permission set: intent ``actions`` minus ``deny``, intersected
    with capability grants. Serialization is deterministic (sorted).
    """

    allowed: frozenset[str] = frozenset()

    def allows(self, action: str) -> bool:
        return action in self.allowed

    def to_dict(self) -> dict[str, list[str]]:
        return {"allowed": sorted(self.allowed)}


@dataclass(frozen=True)
class SecurityDecision:
    """Auditable verdict for a single action under an intent and capabilities."""

    action: str = ""
    allowed: bool = False
    reason: str = ""
    violations: list[str] = field(default_factory=list)
    effective_permissions: EffectivePermissions = field(default_factory=EffectivePermissions)

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "violations": list(self.violations),
            "effective_permissions": self.effective_permissions.to_dict(),
        }
