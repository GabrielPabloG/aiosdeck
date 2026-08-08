"""Architectural contract tests for the security intent subsystem.

These tests freeze the public vocabulary exchanged between the security
layer and the rest of the system:
- ``IntentPolicy`` — the explicit action vocabulary with a deny set.
- ``EffectivePermissions`` — the resolved, ordered permission set.
- ``SecurityDecision`` — the auditable verdict for a single action.

The existing ``AgentCapabilities`` from ``aios.agents.contracts`` is reused
as-is — it is never recreated here.
"""

import json
from dataclasses import FrozenInstanceError

import pytest

from aios.agents.contracts import AgentCapabilities, FILESYSTEM_READ, GIT
from aios.security import EffectivePermissions, IntentPolicy, SecurityDecision


def test_agent_capabilities_is_reused_not_recreated():
    caps = AgentCapabilities.from_list([FILESYSTEM_READ, GIT])
    assert caps.permissions == (FILESYSTEM_READ, GIT)
    assert caps.has(FILESYSTEM_READ)


def test_intent_policy_default_source():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ}))
    assert intent.source == "default"


def test_intent_policy_actions_and_deny_are_frozensets():
    intent = IntentPolicy(
        actions=frozenset({"filesystem.read", "shell.execute"}),
        deny=frozenset({"shell.execute"}),
    )
    assert isinstance(intent.actions, frozenset)
    assert isinstance(intent.deny, frozenset)


def test_intent_policy_is_immutable():
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ}))
    with pytest.raises(FrozenInstanceError):
        intent.actions = frozenset()  # type: ignore[misc]


def test_intent_policy_to_dict_round_trip():
    intent = IntentPolicy(
        name="dev",
        source="user",
        actions=frozenset({"shell.execute", "filesystem.read"}),
        deny=frozenset({"filesystem.delete"}),
    )
    data = intent.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["name"] == "dev"
    assert data["source"] == "user"
    assert data["actions"] == ["filesystem.read", "shell.execute"]
    assert data["deny"] == ["filesystem.delete"]


def test_effective_permissions_allows():
    effective = EffectivePermissions(allowed=frozenset({"filesystem.read", "git.branch"}))
    assert effective.allows("filesystem.read")
    assert not effective.allows("shell.execute")


def test_effective_permissions_to_dict_is_sorted():
    effective = EffectivePermissions(
        allowed=frozenset({"shell.execute", "git.branch", "filesystem.read"})
    )
    data = effective.to_dict()
    assert data["allowed"] == ["filesystem.read", "git.branch", "shell.execute"]


def test_security_decision_to_dict_is_auditable():
    effective = EffectivePermissions(allowed=frozenset({"filesystem.read"}))
    decision = SecurityDecision(
        action="shell.execute",
        allowed=False,
        reason="shell.execute not granted by intent or capability",
        violations=["shell.execute"],
        effective_permissions=effective,
    )
    data = decision.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data == {
        "action": "shell.execute",
        "allowed": False,
        "reason": "shell.execute not granted by intent or capability",
        "violations": ["shell.execute"],
        "effective_permissions": {"allowed": ["filesystem.read"]},
    }
