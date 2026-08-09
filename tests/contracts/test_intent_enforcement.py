"""Contract tests for intent_enforcement — the auditable allow/deny decision.

The security domain owns the decision logic (``validate_intent``); the
AgentExecutor owns enforcement (event publishing, lifecycle, errors).
These tests freeze the decision contract — any change to how an intent is
validated against capabilities must fail here.
"""

from aios.agents.contracts import AgentCapabilities
from aios.security.contracts import IntentPolicy
from aios.security.intent_validator import validate_intent


# ──────────────────────────────────────────────────────────
# Basic allow/deny
# ──────────────────────────────────────────────────────────


def test_intent_with_matching_capabilities_allows():
    """Intent matching capabilities → allowed."""
    intent = IntentPolicy(actions=frozenset({"filesystem.read"}))
    caps = AgentCapabilities.from_list(["filesystem_read"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is True
    assert decision.effective_permissions.allows("filesystem.read")


def test_intent_with_no_matching_capabilities_denies():
    """Intent without overlapping capabilities → denied."""
    intent = IntentPolicy(actions=frozenset({"shell.execute"}))
    caps = AgentCapabilities.from_list(["filesystem_read"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False
    assert not decision.effective_permissions.allows("shell.execute")


def test_intent_with_explicit_deny_excludes_action():
    """Actions present in the deny set are excluded from effective."""
    intent = IntentPolicy(
        actions=frozenset({"filesystem.read", "shell.execute"}),
        deny=frozenset({"shell.execute"}),
    )
    caps = AgentCapabilities.from_list(["filesystem_read", "shell"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is True
    assert decision.effective_permissions.allows("filesystem.read")
    assert not decision.effective_permissions.allows("shell.execute")


def test_intent_deny_everything_denies():
    """When deny covers all actions → denied even if capabilities include them."""
    intent = IntentPolicy(
        actions=frozenset({"filesystem.read"}),
        deny=frozenset({"filesystem.read"}),
    )
    caps = AgentCapabilities.from_list(["filesystem_read"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False


# ──────────────────────────────────────────────────────────
# Decision shape
# ──────────────────────────────────────────────────────────


def test_denied_decision_has_violations():
    """When denied, violations list the granted capabilities."""
    intent = IntentPolicy(actions=frozenset({"git.push"}))
    caps = AgentCapabilities.from_list(["filesystem_read", "git"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False
    assert "filesystem.read" in decision.violations
    assert "git.branch" in decision.violations
    assert "git.commit" in decision.violations


def test_allowed_decision_has_effective_permissions():
    """When allowed, effective_permissions carries the resolved set."""
    intent = IntentPolicy(actions=frozenset({"filesystem.read", "shell.execute"}))
    caps = AgentCapabilities.from_list(["filesystem_read", "shell"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is True
    assert decision.effective_permissions.allows("filesystem.read")
    assert decision.effective_permissions.allows("shell.execute")


def test_allowed_decision_has_no_violations():
    """Allowed decisions have an empty violations list."""
    intent = IntentPolicy(actions=frozenset({"filesystem.read"}))
    caps = AgentCapabilities.from_list(["filesystem_read"])
    decision = validate_intent(intent, caps)
    assert decision.violations == []


# ──────────────────────────────────────────────────────────
# Capability expansion is deterministic
# ──────────────────────────────────────────────────────────


def test_coarse_ability_expands_to_granular():
    """A coarse capability like 'shell' expands to 'shell.execute'."""
    intent = IntentPolicy(actions=frozenset({"shell.execute"}))
    caps = AgentCapabilities.from_list(["shell"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is True


def test_git_capability_does_not_expand_to_push():
    """git capability expands to branch+commit, NOT push."""
    intent = IntentPolicy(actions=frozenset({"git.push"}))
    caps = AgentCapabilities.from_list(["git"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False


def test_empty_intent_always_denies():
    """No actions requested → denied (nothing allowed)."""
    intent = IntentPolicy(actions=frozenset())
    caps = AgentCapabilities.from_list(["filesystem_read", "shell"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False


def test_idempotent():
    """Multiple calls with the same inputs produce identical decisions."""
    intent = IntentPolicy(actions=frozenset({"filesystem.read"}))
    caps = AgentCapabilities.from_list(["filesystem_read"])
    a = validate_intent(intent, caps)
    b = validate_intent(intent, caps)
    assert a.allowed == b.allowed
    assert a.effective_permissions.to_dict() == b.effective_permissions.to_dict()


# ──────────────────────────────────────────────────────────
# Integration with real agent capabilities
# ──────────────────────────────────────────────────────────


def test_planner_caps_allow_read_only():
    """Planner caps (filesystem_read, ask_user) expand correctly."""
    intent = IntentPolicy(actions=frozenset({"filesystem.read", "ask_user"}))
    caps = AgentCapabilities.from_list(["filesystem_read", "ask_user"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is True
    assert decision.effective_permissions.allows("filesystem.read")
    assert decision.effective_permissions.allows("ask_user")


def test_planner_caps_deny_write():
    """Planner caps never grant filesystem.write or shell.execute."""
    intent = IntentPolicy(actions=frozenset({"filesystem.write", "shell.execute"}))
    caps = AgentCapabilities.from_list(["filesystem_read", "ask_user"])
    decision = validate_intent(intent, caps)
    assert decision.allowed is False
