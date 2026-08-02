"""Runtime Engine — manages the runtime adapter lifecycle.

In v0.2, execute() uses a simulated runtime. Real OpenCode invocation
via ai-jail will be implemented in v0.5+.
"""

import logging

from aios.runtime.opencode import OpenCodeAdapter

logger = logging.getLogger("aios.runtime")


class RuntimeEngine:
    name = "runtime"

    def __init__(self, adapter: OpenCodeAdapter | None = None) -> None:
        self.adapter = adapter or OpenCodeAdapter()

    def initialize(self) -> None:
        self.adapter.initialize()

    def health_check(self) -> bool:
        return self.adapter.health_check()

    def shutdown(self) -> None:
        self.adapter.shutdown()

    @property
    def command(self) -> str:
        return self.adapter.command

    @property
    def has_sandbox(self) -> bool:
        return self.adapter.has_sandbox

    def execute(self, prompt: str, skills: list[str]) -> str:
        """Execute a prompt via the runtime adapter."""
        return self.adapter.execute(prompt, skills)
