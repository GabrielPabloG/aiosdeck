"""GitAgent — safe local git operations behind a task-dispatched execute().

Responsibilities:
- Provide safe local git operations: stage, commit, create tag.
- Prevent pushing to remotes unless an explicit approval flag is provided.

Executor-free by design: the AgentExecutor invokes ``execute()``; the git
operations live behind private ``_stage/_commit/...`` methods.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aios.agents.base import BaseAgent
from aios.agents.contracts import RUNTIME_ERROR, AgentError, coerce_task
from aios.agents.models import AgentResult


@dataclass(frozen=True)
class GitOperation:
    """Result payload from the Git agent (command, exit code, output)."""

    command: list[str]
    executed: bool
    stdout: str
    stderr: str
    returncode: int

    def to_dict(self) -> dict:
        return {
            "command": list(self.command),
            "executed": self.executed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }


class GitAgent(BaseAgent):
    """Performs version-control operations: branch, stage, commit.
    Push requires explicit human approval."""

    name = "git"
    timeout = 90.0
    required_capabilities = ["git"]
    required_skills: list[str] = []

    def __init__(self, repository: Path | str = ".") -> None:
        super().__init__()
        self._repository = Path(repository)

    def execute(self, task, context) -> AgentResult:
        """Contract method — the operation and params arrive via the AgentTask."""
        agent_task = coerce_task(task)
        operation = agent_task.params.get("operation") or agent_task.task_type
        try:
            result = self._dispatch(operation, agent_task.params)
        except (KeyError, ValueError) as exc:
            return AgentResult(
                success=False,
                errors=[str(exc)],
                error=AgentError(code=RUNTIME_ERROR, message=str(exc)),
                error_code=RUNTIME_ERROR,
                agent=self.name,
                task_id=agent_task.task_id,
                correlation_id=agent_task.correlation_id,
            )
        return AgentResult(
            success=result.returncode == 0,
            output=json.dumps(result.to_dict(), indent=2),
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )

    def _dispatch(self, operation: str, params: dict) -> GitOperation:
        if operation == "stage":
            return self._stage(params.get("paths"))
        if operation == "commit":
            return self._commit(params["message"])
        if operation == "create_branch":
            return self._create_branch(params["name"])
        if operation == "create_tag":
            return self._create_tag(params["name"])
        if operation == "push":
            return self._push(approved=params.get("approved", False))
        raise ValueError(f"unknown git operation: {operation}")

    def _stage(self, paths: list[str] | None = None) -> GitOperation:
        command = ["git", "add"]
        command.extend(paths or ["."])
        return self._run(command)

    def _commit(self, message: str) -> GitOperation:
        return self._run(["git", "commit", "-m", message])

    def _create_branch(self, name: str) -> GitOperation:
        return self._run(["git", "checkout", "-b", name])

    def _create_tag(self, name: str) -> GitOperation:
        return self._run(["git", "tag", name])

    def _push(self, approved: bool = False) -> GitOperation:
        command = ["git", "push"]
        if not approved:
            return GitOperation(
                command=command,
                executed=False,
                stdout="",
                stderr="",
                returncode=0,
            )
        return self._run(command)

    def _run(self, command: list[str]) -> GitOperation:
        try:
            result = subprocess.run(
                command,
                cwd=self._repository,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError as exc:
            return GitOperation(
                command=command,
                executed=True,
                stdout="",
                stderr=f"git not available: {exc}",
                returncode=-1,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return GitOperation(
                command=command,
                executed=True,
                stdout="",
                stderr=str(exc),
                returncode=-1,
            )
        return GitOperation(
            command=command,
            executed=True,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
