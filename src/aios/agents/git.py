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

# A porcelain record is "<XY> <path>": two status chars, one space, then path.
_PORCELAIN_HEADER = 3


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
        if operation == "status":
            return self._status()
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

    def status(self) -> GitOperation:
        """Report the change set as ``git status --porcelain=v1 -z`` output.

        ``_changed_files()`` is the canonical consumer; the raw porcelain is
        kept on the payload for transparency.
        """
        return self._run(["git", "status", "--porcelain=v1", "-z"])

    def _status(self) -> GitOperation:
        return self.status()

    def _changed_files(self) -> list[str]:
        """Parsed changed paths (tracked modifications + untracked files).

        Uses the NUL-delimited ``porcelain=v1`` format so paths containing
        spaces are parsed reliably. Renames resolve to the new path; deletions
        are excluded (a removed file cannot carry a new implementation).
        """
        raw = self.status().stdout
        return _parse_porcelain(raw)

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


def _parse_porcelain(raw: str) -> list[str]:
    """Parse ``git status --porcelain=v1 -z`` output into changed paths.

    Entries are NUL-delimited so paths containing spaces are safe (and unquoted).
    Each record begins with a two-character status followed by a single space
    and the path. In ``-z`` mode a rename/copy spans two records: the first is
    ``<status> <to>`` (the destination/new path) and the second is ``<from>``
    (the source/old path, no status). Only the resulting (new) path is reported;
    deletions are dropped because a removed file cannot carry a new change.
    """
    if not raw:
        return []
    paths: list[str] = []
    records = [r for r in raw.split("\0") if r]
    i = 0
    while i < len(records):
        record = records[i]
        if len(record) < _PORCELAIN_HEADER:
            i += 1
            continue
        xy = record[0:2]
        path = record[_PORCELAIN_HEADER:]
        if xy[0] in "RC":
            # First record already carries the destination (new) path; the
            # following record is the source (old) path and is skipped.
            i += 2
        elif "D" in xy:
            i += 1
            continue
        else:
            i += 1
        if path:
            paths.append(path)
    return paths
