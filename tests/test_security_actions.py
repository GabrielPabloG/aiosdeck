"""Tests for the granular security action vocabulary and capability expansion.

Freezes the additive, deterministic expansion table and the safe defaults:
- every known coarse capability expands to a non-empty set of granular actions
- ``filesystem_write`` never implies ``filesystem.delete``
- ``git`` never implies ``push``/``tag``
- unknown capabilities fail safe to the empty set (never raise)
- ``DEFAULT_INTENTS`` never grant destructive/privileged actions; ``release``
  has no default and must come from an explicit override.
"""

from aios.agents.contracts import (
    AgentCapabilities,
    ASK_USER,
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
    GIT,
    INTERNET,
    SHELL,
)
from aios.security.actions import (
    ASK_USER_ACTION,
    CAPABILITY_ACTIONS,
    DEFAULT_INTENTS,
    FILESYSTEM_DELETE,
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    GIT_BRANCH,
    GIT_COMMIT,
    GIT_PUSH,
    GIT_TAG,
    NETWORK_ACCESS,
    RELEASE_PUBLISH,
    SHELL_EXECUTE,
    expand,
)

_KNOWN = (FILESYSTEM_READ, FILESYSTEM_WRITE, SHELL, GIT, INTERNET, ASK_USER)


def test_every_known_capability_expands_to_non_empty_set():
    for capability in _KNOWN:
        assert CAPABILITY_ACTIONS[capability]
        assert expand(capability)


def test_filesystem_write_does_not_imply_delete():
    assert FILESYSTEM_DELETE not in expand(FILESYSTEM_WRITE)


def test_git_does_not_imply_push_or_tag():
    granted = expand(GIT)
    assert GIT_PUSH not in granted
    assert GIT_TAG not in granted


def test_internet_maps_to_network_access():
    assert expand(INTERNET) == frozenset({NETWORK_ACCESS})


def test_ask_user_maps_to_ask_user_action():
    assert expand(ASK_USER) == frozenset({ASK_USER_ACTION})


def test_unknown_capability_fails_safe_to_empty_set():
    assert expand("unknown_capability") == frozenset()
    assert expand("") == frozenset()


def test_expand_accepts_agent_capabilities_and_list():
    caps = AgentCapabilities.from_list([FILESYSTEM_READ, GIT])
    assert expand(caps) == frozenset({FILESYSTEM_READ_ACTION, GIT_BRANCH, GIT_COMMIT})
    assert expand([FILESYSTEM_READ, SHELL]) == frozenset({FILESYSTEM_READ_ACTION, SHELL_EXECUTE})


def test_expand_union_is_additive():
    combined = expand([FILESYSTEM_READ, FILESYSTEM_WRITE])
    assert combined == frozenset({FILESYSTEM_READ_ACTION, FILESYSTEM_WRITE_ACTION})


def test_develop_default_never_grants_destructive_or_privileged_actions():
    develop = DEFAULT_INTENTS["develop"]
    privileged = {FILESYSTEM_DELETE, GIT_PUSH, GIT_TAG, NETWORK_ACCESS, RELEASE_PUBLISH}
    assert develop.actions.isdisjoint(privileged)
    assert develop.name == "develop"


def test_default_intent_vocabulary_is_safe():
    safe = {
        FILESYSTEM_READ_ACTION,
        FILESYSTEM_WRITE_ACTION,
        SHELL_EXECUTE,
        GIT_BRANCH,
        GIT_COMMIT,
        ASK_USER_ACTION,
    }
    for intent in DEFAULT_INTENTS.values():
        assert intent.actions <= safe
        assert intent.deny == frozenset()


def test_release_has_no_default_intent():
    assert "release" not in DEFAULT_INTENTS


def test_default_intents_serialize_deterministically():
    for intent in DEFAULT_INTENTS.values():
        data = intent.to_dict()
        assert data["actions"] == sorted(data["actions"])
