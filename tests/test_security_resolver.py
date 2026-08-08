"""Tests for the effective-permission resolver and security decisions.

These are the critical review tests. The frozen semantics:

- ``effective = (intent.actions - intent.deny) ∩ expand(capabilities)``
- deny = absence: any action missing from the intent OR the capabilities is
  denied; an explicit ``deny`` always wins.
- an intent can never elevate capabilities (intersection).
- ``decide()`` always returns a full, auditable ``SecurityDecision``.
"""

from aios.agents.contracts import (
    AgentCapabilities,
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
    GIT,
    SHELL,
)
from aios.security import IntentPolicy, decide, effective_permissions
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    GIT_BRANCH,
    GIT_PUSH,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
)


def _caps(*permissions: str) -> AgentCapabilities:
    return AgentCapabilities.from_list(list(permissions))


def test_effective_permissions_is_intersection():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION, FILESYSTEM_WRITE_ACTION}))
    effective = effective_permissions(intent, _caps(FILESYSTEM_READ))
    assert effective == frozenset({FILESYSTEM_READ_ACTION})


def test_action_not_in_intent_is_denied():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    effective = effective_permissions(intent, _caps(FILESYSTEM_READ, FILESYSTEM_WRITE))
    assert FILESYSTEM_WRITE_ACTION not in effective


def test_action_not_in_capability_is_denied():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_WRITE_ACTION}))
    effective = effective_permissions(intent, _caps(FILESYSTEM_READ))
    assert FILESYSTEM_WRITE_ACTION not in effective


def test_explicit_deny_wins_over_intent_and_capability():
    intent = IntentPolicy(
        actions=frozenset({GIT_BRANCH, GIT_PUSH}),
        deny=frozenset({GIT_PUSH}),
    )
    effective = effective_permissions(intent, _caps(GIT))
    assert effective == frozenset({GIT_BRANCH})


def test_permissive_intent_cannot_elevate_capabilities():
    intent = IntentPolicy(actions=frozenset({NETWORK_ACCESS}))
    decision = decide(NETWORK_ACCESS, intent, _caps(FILESYSTEM_READ))
    assert decision.allowed is False
    assert decision.violations == [NETWORK_ACCESS]


def test_high_capability_agent_is_blocked_by_restricted_intent():
    review_intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    effective = effective_permissions(review_intent, _caps(FILESYSTEM_READ, SHELL, GIT))
    assert GIT_BRANCH not in effective
    assert SHELL_EXECUTE not in effective
    assert effective == frozenset({FILESYSTEM_READ_ACTION})


def test_decide_allowed():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    decision = decide(FILESYSTEM_READ_ACTION, intent, _caps(FILESYSTEM_READ))
    assert decision.allowed is True
    assert decision.reason
    assert decision.violations == []
    assert decision.effective_permissions.allows(FILESYSTEM_READ_ACTION)


def test_decide_denied_always_has_reason_and_violations():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    decision = decide(SHELL_EXECUTE, intent, _caps(FILESYSTEM_READ, SHELL))
    assert decision.allowed is False
    assert decision.reason
    assert decision.violations == [SHELL_EXECUTE]


def test_decide_is_deterministic():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION, SHELL_EXECUTE, GIT_BRANCH}))
    first = decide(SHELL_EXECUTE, intent, _caps(FILESYSTEM_READ, SHELL, GIT))
    second = decide(SHELL_EXECUTE, intent, _caps(FILESYSTEM_READ, SHELL, GIT))
    assert first.to_dict() == second.to_dict()
    assert first.effective_permissions.to_dict() == second.effective_permissions.to_dict()
