"""Granular security action vocabulary and capability expansion.

Agent capabilities remain coarse and intact (``filesystem_read``, ``shell``,
``git``, ...); this module maps each coarse capability to the set of granular
actions it grants. Expansion is additive and deterministic, and any capability
with no mapping grants nothing (fail-safe: never raises).

``DEFAULT_INTENTS`` are the safe built-in intents pinned by tests. They never
grant destructive or privileged actions (``filesystem.delete``, ``git.push``,
``git.tag``, ``network.access``, ``release.publish``) — those only enter via an
explicit intent override. ``release`` intentionally has no default.
"""

from aios.agents.contracts import (
    ASK_USER,
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
    GIT,
    INTERNET,
    SHELL,
    AgentCapabilities,
)
from aios.security.contracts import IntentPolicy

# ---------------------------------------------------------------------------
# Granular action vocabulary
# ---------------------------------------------------------------------------

FILESYSTEM_READ_ACTION = "filesystem.read"
FILESYSTEM_WRITE_ACTION = "filesystem.write"
FILESYSTEM_DELETE = "filesystem.delete"
SHELL_EXECUTE = "shell.execute"
GIT_BRANCH = "git.branch"
GIT_COMMIT = "git.commit"
GIT_PUSH = "git.push"
GIT_TAG = "git.tag"
NETWORK_ACCESS = "network.access"
ASK_USER_ACTION = "ask_user"
RELEASE_PUBLISH = "release.publish"

# ---------------------------------------------------------------------------
# Additive, deterministic expansion table
# ---------------------------------------------------------------------------

CAPABILITY_ACTIONS: dict[str, frozenset[str]] = {
    FILESYSTEM_READ: frozenset({FILESYSTEM_READ_ACTION}),
    FILESYSTEM_WRITE: frozenset({FILESYSTEM_WRITE_ACTION}),
    SHELL: frozenset({SHELL_EXECUTE}),
    GIT: frozenset({GIT_BRANCH, GIT_COMMIT}),
    INTERNET: frozenset({NETWORK_ACCESS}),
    ASK_USER: frozenset({ASK_USER_ACTION}),
}


def expand(capabilities: AgentCapabilities | list[str] | str) -> frozenset[str]:
    """Expand coarse capabilities into the granular actions they grant.

    Accepts an ``AgentCapabilities``, a list of coarse capability names, or a
    single coarse capability name. Unknown capabilities grant nothing — the
    result is the additive union, fail-safe.
    """
    if isinstance(capabilities, AgentCapabilities):
        names = capabilities.permissions
    elif isinstance(capabilities, str):
        names = (capabilities,)
    else:
        names = capabilities
    granted: frozenset[str] = frozenset()
    for capability in names:
        granted |= CAPABILITY_ACTIONS.get(capability, frozenset())
    return granted


# ---------------------------------------------------------------------------
# Safe built-in intents (pinned by tests)
# ---------------------------------------------------------------------------

DEFAULT_INTENTS: dict[str, IntentPolicy] = {
    "plan": IntentPolicy(
        name="plan",
        actions=frozenset({FILESYSTEM_READ_ACTION, ASK_USER_ACTION}),
    ),
    "review": IntentPolicy(name="review", actions=frozenset({FILESYSTEM_READ_ACTION})),
    "research": IntentPolicy(
        name="research",
        actions=frozenset({FILESYSTEM_READ_ACTION}),
    ),
    "develop": IntentPolicy(
        name="develop",
        actions=frozenset(
            {
                FILESYSTEM_READ_ACTION,
                FILESYSTEM_WRITE_ACTION,
                SHELL_EXECUTE,
                GIT_BRANCH,
                GIT_COMMIT,
            }
        ),
    ),
    "test": IntentPolicy(
        name="test",
        actions=frozenset({FILESYSTEM_READ_ACTION, SHELL_EXECUTE}),
    ),
}

# Runtime intent for the workflow pipeline: the develop defaults plus
# ``ask_user`` (the planner's reasoning loop needs it). Agent capabilities stay
# coarse and bound the effective set per agent, so this can never elevate.
WORKFLOW_INTENT = IntentPolicy(
    name=DEFAULT_INTENTS["develop"].name,
    source=DEFAULT_INTENTS["develop"].source,
    actions=DEFAULT_INTENTS["develop"].actions | frozenset({ASK_USER_ACTION}),
)
