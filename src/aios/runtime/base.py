"""Runtime adapter protocol."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aios.security.contracts import EffectivePermissions


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Protocol that every runtime adapter must implement."""

    name: str
    version: str

    def initialize(self) -> None: ...
    def health_check(self) -> bool: ...
    def shutdown(self) -> None: ...

    @property
    def command(self) -> str:
        """The resolved runtime command (with sandbox)."""
        ...

    def execute(
        self,
        prompt: str,
        skills: list[str],
        capabilities: list[str] | None = None,
        permissions: EffectivePermissions | None = None,
    ) -> str:
        """Execute a prompt with the runtime. Returns raw output.

        Args:
            prompt: The prompt to send to the runtime.
            skills: Skill names to load for this execution.
            capabilities: Agent capabilities (e.g. filesystem_read, shell).
                          Used to lock down tool permissions in headless mode
                          when no resolved permissions are provided.
            permissions: Resolved effective permissions from the security
                         layer. When provided, the tool policy is derived from
                         these; ``None`` falls back to the coarse capabilities.
        """
        ...
