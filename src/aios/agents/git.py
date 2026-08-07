"""Minimal GitAgent scaffold.

Responsibilities:
- Provide safe local git operations: stage, commit, create tag.
- Prevent pushing to remotes unless explicit approval flag is provided.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from aios.agents.base import BaseAgent


@dataclass(frozen=True)
class GitOperation:
    command: list[str]
    executed: bool
    stdout: str
    stderr: str
    returncode: int


class GitAgent(BaseAgent):
    name = "git"
    required_capabilities = ["git"]
    required_skills: list[str] = []

    def __init__(self, repository: Path | str = ".") -> None:
        self._repository = Path(repository)

    def stage(self, paths: list[str] | None = None) -> GitOperation:
        command = ["git", "add"]
        command.extend(paths or ["."])
        return self._run(command)

    def commit(self, message: str) -> GitOperation:
        return self._run(["git", "commit", "-m", message])

    def create_branch(self, name: str) -> GitOperation:
        return self._run(["git", "checkout", "-b", name])

    def create_tag(self, name: str) -> GitOperation:
        return self._run(["git", "tag", name])

    def push(self, approved: bool = False) -> GitOperation:
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
