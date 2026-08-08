"""Base agent implementation.

Agents are executor-free: they never hold or call an ``AgentExecutor``. The
AgentExecutor is the single execution boundary and it invokes ``execute()``.
``BaseAgent`` only declares metadata, capabilities, and the contract method.
"""

from aios.agents.contracts import AgentCapabilities, AgentError, AgentMetadata, RetryPolicy
from aios.agents.models import AgentResult


class BaseAgent:
    name: str = "base"
    version: str = "1.0"
    timeout: float | None = None
    retry_policy: RetryPolicy = RetryPolicy()
    required_capabilities: list[str] = ["filesystem_read"]
    required_skills: list[str] = []

    def __init__(self) -> None:
        self.metadata = AgentMetadata(
            name=self.name,
            version=self.version,
            timeout=self.timeout,
            retry_policy=self.retry_policy,
        )
        self.capabilities = AgentCapabilities.from_list(self.required_capabilities)

    def initialize(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def execute(self, task, context) -> AgentResult:
        raise NotImplementedError

    @staticmethod
    def _failure(message: str, code: str = "RUNTIME_ERROR") -> AgentResult:
        return AgentResult(
            success=False,
            errors=[message],
            error=AgentError(code=code, message=message, transient=False),
            error_code=code,
        )
