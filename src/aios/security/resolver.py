"""Effective-permission resolver and security decisions.

An action is allowed only when it survives the intent (present in ``actions``
and absent from ``deny``) AND is granted by the capabilities: ``effective =
(intent.actions - intent.deny) ∩ expand(capabilities)``. ``decide()`` turns
that resolution into an auditable ``SecurityDecision`` for a single action.
"""

from aios.agents.contracts import AgentCapabilities
from aios.security.actions import expand
from aios.security.contracts import EffectivePermissions, IntentPolicy, SecurityDecision


def effective_permissions(
    intent: IntentPolicy,
    capabilities: AgentCapabilities | list[str] | str,
) -> frozenset[str]:
    """Return the effective granular actions for an intent and capabilities."""
    granted = expand(capabilities)
    return (intent.actions - intent.deny) & granted


def decide(
    action: str,
    intent: IntentPolicy,
    capabilities: AgentCapabilities | list[str] | str,
) -> SecurityDecision:
    """Resolve a single action and return the auditable verdict."""
    effective = effective_permissions(intent, capabilities)
    allowed = action in effective
    if allowed:
        reason = f"{action} granted by intent and capabilities"
        violations: list[str] = []
    else:
        reason = (
            f"{action} denied: not in intent, explicitly denied, or not granted by capabilities"
        )
        violations = [action]
    return SecurityDecision(
        action=action,
        allowed=allowed,
        reason=reason,
        violations=violations,
        effective_permissions=EffectivePermissions(allowed=effective),
    )
