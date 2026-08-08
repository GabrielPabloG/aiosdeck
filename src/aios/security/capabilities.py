"""Capability enforcement — validates agent capabilities against canonical policy.

The canonical policy is the source of truth for what every agent may declare.
The ``CapabilityEnforcer`` is invoked by the AgentExecutor before running an
agent: any capability an agent declares that the policy does not grant results
in ``PERMISSION_DENIED``. Read-only agents can never gain write/shell/internet
because their declared set must be a subset of the policy grants.
"""

from aios.agents.contracts import (
    FILESYSTEM_READ,
    FILESYSTEM_WRITE,
    GIT,
    INTERNET,
    SHELL,
)

# Canonical capability grants per agent name.
CANONICAL_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "planner": (FILESYSTEM_READ, "ask_user"),
    "research": (FILESYSTEM_READ,),
    "developer": (FILESYSTEM_READ, FILESYSTEM_WRITE, SHELL),
    "reviewer": (FILESYSTEM_READ,),
    "tester": (FILESYSTEM_READ, SHELL),
    "documentation": (FILESYSTEM_READ, FILESYSTEM_WRITE),
    "git": (GIT,),
}

# Capabilities that require explicit policy grants (never implicit).
_PRIVILEGED = (FILESYSTEM_WRITE, SHELL, GIT, INTERNET)


class CapabilityEnforcer:
    """Validates that an agent's declared capabilities match the policy."""

    def __init__(self, policy: dict[str, tuple[str, ...]] | None = None) -> None:
        self._policy = policy or CANONICAL_CAPABILITIES

    @property
    def policy(self) -> dict[str, tuple[str, ...]]:
        return dict(self._policy)

    def validate(self, agent) -> None:
        """Raise PermissionError when the agent declares non-granted capabilities."""
        declared = set(agent.capabilities.permissions)
        granted = set(self._policy.get(agent.name, ()))
        extra = declared - granted
        if extra:
            raise PermissionError(
                f"agent '{agent.name}' declares capabilities not granted by policy: {sorted(extra)}"
            )

    def validate_agent(self, name: str, permissions: list[str]) -> None:
        """Static form — validate by name and permission list without an agent."""
        declared = set(permissions)
        granted = set(self._policy.get(name, ()))
        extra = declared - granted
        if extra:
            raise PermissionError(
                f"agent '{name}' declares capabilities not granted by policy: {sorted(extra)}"
            )
