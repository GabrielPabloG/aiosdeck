"""Intent enforcement — the auditable decision of allow/deny.

The AgentExecutor delegates intent enforcement to this module so every
allow/deny decision is computed in a single, auditable place (the security
domain). The executor owns enforcement — event publishing, lifecycle
transitions, error creation — but the decision of *whether* an intent is
valid against agent capabilities is made here.

All functions are deterministic, pure, and testable in isolation.
"""

from aios.security.contracts import EffectivePermissions, IntentPolicy, SecurityDecision


def validate_intent(intent: IntentPolicy, capabilities: object) -> SecurityDecision:
    """Decide whether an IntentPolicy is valid against agent capabilities.

    Computes effective = (intent.actions - intent.deny) ∩ expand(capabilities).
    Returns a ``SecurityDecision``: ``allowed=True`` when at least one
    effective action remains; ``allowed=False`` otherwise, with the full
    set of granted actions as ``violations``.

    Args:
        intent: The run's IntentPolicy (actions + deny set).
        capabilities: An AgentCapabilities, list of coarse capability names,
            or single coarse capability name.

    Returns:
        An auditable SecurityDecision. Callers consume ``decision.allowed``
        and ``decision.effective_permissions``.
    """
    from aios.security.actions import expand  # noqa: PLC0415 — deferred to avoid circular import

    granted = expand(capabilities)
    effective = (intent.actions - intent.deny) & granted
    intent_name = intent.name or "unknown"

    if not effective:
        return SecurityDecision(
            action=intent_name,
            allowed=False,
            reason=f"intent '{intent_name}' grants no action",
            violations=sorted(granted),
            effective_permissions=EffectivePermissions(allowed=frozenset()),
        )

    return SecurityDecision(
        action=intent_name,
        allowed=True,
        reason=f"intent '{intent_name}' grants actions",
        effective_permissions=EffectivePermissions(allowed=effective),
    )
