"""Base agent implementation."""

from aios.agents import AgentResult


class BaseAgent:
    name: str = "base"
    required_capabilities: list[str] = ["filesystem_read"]
    required_skills: list[str] = []

    def initialize(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def execute(self, task, context) -> AgentResult:
        raise NotImplementedError
