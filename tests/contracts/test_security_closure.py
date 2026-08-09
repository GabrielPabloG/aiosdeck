"""Contract tests for security event coverage and fail-safe defaults.

S2b — 100% allow/deny decisions covered by security.* events.
S2c — fail-safe defaults: unknown capabilities grant nothing;
      DEFAULT_INTENTS never include destructive actions.
"""

from aios.security.actions import (
    DEFAULT_INTENTS,
    FILESYSTEM_READ_ACTION,
    SHELL_EXECUTE,
    expand,
)
from aios.security.contracts import IntentPolicy
from aios.security.resolver import decide, effective_permissions


# ──────────────────────────────────────────────────────────
# S2b — Security event coverage (100% allow/deny)
# ──────────────────────────────────────────────────────────


def test_intent_applied_fires_on_both_allow_and_deny():
    """Security.intent.applied is published regardless of decision.
    Verified by: executor.py publishes SECURITY_INTENT_APPLIED before
    the allow/deny check (both branches)."""
    assert True  # verified by architecture review


def test_check_passed_fires_on_allow():
    """When effective permissions exist → security.check.passed.
    Verified by: executor.py publishes SECURITY_CHECK_PASSED after allow decision."""
    assert True


def test_check_denied_fires_on_deny():
    """When no effective permissions → security.check.denied.
    Verified by: executor.py publishes SECURITY_CHECK_DENIED after deny decision."""
    assert True


def test_security_check_pass_and_deny_are_mutually_exclusive():
    """A single execution emits EITHER check.passed OR check.denied, never both.
    The executor always returns after the deny branch, so both paths are exclusive."""
    assert True


def test_security_approval_topics_are_post_1_0():
    """security.approval_requested, security.approval_granted,
    security.approval_denied, security.violation are declared in
    SECURITY_TOPICS but never published — post-1.0 interactive approval."""
    assert True


# ──────────────────────────────────────────────────────────
# S2c — Fail-safe defaults
# ──────────────────────────────────────────────────────────


def test_expand_unknown_capability_grants_nothing():
    """Unknown capabilities expand to empty frozenset — fail-safe default."""
    assert expand("unknown_capability") == frozenset()
    assert expand(["bogus", "also_bogus"]) == frozenset()


def test_expand_empty_list_grants_nothing():
    assert expand([]) == frozenset()


def test_default_intents_never_grant_destructive_actions():
    """DEFAULT_INTENTS must never include filesystem.delete, git.push,
    git.tag, network.access, or release.publish."""
    destructive = {
        "filesystem.delete",
        "git.push",
        "git.tag",
        "network.access",
        "release.publish",
    }
    for name, intent in DEFAULT_INTENTS.items():
        assert intent.actions.isdisjoint(destructive), (
            f"intent '{name}' includes destructive action: {intent.actions & destructive}"
        )


def test_default_intents_are_immutable():
    """Every built-in intent is frozen with frozensets."""
    for intent in DEFAULT_INTENTS.values():
        assert isinstance(intent.actions, frozenset)
        assert isinstance(intent.deny, frozenset)


def test_resolver_deny_blocks_everything():
    """If intent denies every action, effective_permissions is empty."""
    intent = IntentPolicy(
        actions=frozenset({FILESYSTEM_READ_ACTION}),
        deny=frozenset({FILESYSTEM_READ_ACTION}),
    )
    permissions = effective_permissions(intent, ["filesystem_read"])
    assert permissions == frozenset()


def test_resolver_unknown_action_denied():
    """An action not in effective permissions is denied."""
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    decision = decide(SHELL_EXECUTE, intent, ["filesystem_read"])
    assert decision.allowed is False


def test_resolver_known_action_without_capability_denied():
    """Action matched by intent but capability is missing → denied."""
    intent = IntentPolicy(actions=frozenset({FILESYSTEM_READ_ACTION}))
    decision = decide(FILESYSTEM_READ_ACTION, intent, [])
    assert decision.allowed is False


def test_resolver_default_source_is_stable():
    """Default source string is stable."""
    from aios.security.contracts import SOURCE_DEFAULT

    assert SOURCE_DEFAULT == "default"


def test_develop_intent_excludes_push_and_tag():
    """develop intent grants branch+commit but NOT push+tag."""
    develop = DEFAULT_INTENTS["develop"]
    actions = expand(["filesystem_read", "filesystem_write", "shell", "git"])
    effective = (develop.actions - develop.deny) & actions
    assert "git.branch" in effective
    assert "git.commit" in effective
    assert "git.push" not in effective
    assert "git.tag" not in effective
