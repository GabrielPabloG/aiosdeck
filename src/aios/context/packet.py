"""Context packet — the standardized output of the Context Engine."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aios.memory.models import ProjectKnowledge


@dataclass
class GitInfo:
    branch: str = ""
    status: str = "unknown"
    remote: str = ""
    last_commit: str = ""
    last_commit_message: str = ""

    @classmethod
    def detect(cls, project_path: Path) -> GitInfo:
        git_dir = project_path / ".git"
        if not git_dir.exists():
            return cls()

        def _run(args: list[str]) -> str:
            try:
                result = subprocess.run(
                    ["git"] + args,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                return result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                return ""

        return cls(
            branch=_run(["rev-parse", "--abbrev-ref", "HEAD"]),
            status="clean" if not _run(["status", "--porcelain"]) else "dirty",
            remote=_run(["remote", "get-url", "origin"]),
            last_commit=_run(["rev-parse", "--short", "HEAD"]),
            last_commit_message=_run(["log", "-1", "--format=%s"]),
        )


@dataclass
class DockerInfo:
    installed: bool = False
    running: bool = False
    compose_files: list[str] = field(default_factory=list)

    @classmethod
    def detect(cls, project_path: Path) -> DockerInfo:
        compose_patterns = [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
        compose_files = []
        for pattern in compose_patterns:
            fpath = project_path / pattern
            if fpath.exists():
                compose_files.append(str(fpath.name))

        docker_installed = shutil.which("docker") is not None
        docker_running = False
        if docker_installed:
            try:
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                docker_running = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass

        return cls(
            installed=docker_installed,
            running=docker_running,
            compose_files=compose_files,
        )


@dataclass
class ToolsInfo:
    dependency_manager: str = ""
    linter: str = ""
    formatter: str = ""
    test_runner: str = ""


@dataclass
class RuntimeInfo:
    opencode: bool = False
    ai_jail: bool = False

    @classmethod
    def detect(cls) -> RuntimeInfo:
        return cls(
            opencode=shutil.which("opencode") is not None,
            ai_jail=shutil.which("ai-jail") is not None,
        )


@dataclass
class StructureInfo:
    has_readme: bool = False
    has_license: bool = False
    has_tests_dir: bool = False
    has_docs_dir: bool = False

    @classmethod
    def detect(cls, project_path: Path) -> StructureInfo:
        return cls(
            has_readme=(project_path / "README.md").exists(),
            has_license=(project_path / "LICENSE").exists(),
            has_tests_dir=(project_path / "tests").is_dir() or (project_path / "test").is_dir(),
            has_docs_dir=(project_path / "docs").is_dir(),
        )


@dataclass
class ProjectInfo:
    name: str = ""
    root: str = ""
    language: str = "unknown"


@dataclass
class ContextPacket:
    project: ProjectInfo = field(default_factory=ProjectInfo)
    tools: ToolsInfo = field(default_factory=ToolsInfo)
    git: GitInfo = field(default_factory=GitInfo)
    docker: DockerInfo = field(default_factory=DockerInfo)
    runtime: RuntimeInfo = field(default_factory=RuntimeInfo)
    structure: StructureInfo = field(default_factory=StructureInfo)
    skills: list[str] = field(default_factory=list)
    memory: ProjectKnowledge | None = field(default=None)
    research: dict | None = field(default=None)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": {
                "name": self.project.name,
                "root": self.project.root,
                "language": self.project.language,
            },
            "tools": {
                "dependency_manager": self.tools.dependency_manager,
                "linter": self.tools.linter,
                "formatter": self.tools.formatter,
                "test_runner": self.tools.test_runner,
            },
            "git": {
                "branch": self.git.branch,
                "status": self.git.status,
                "remote": self.git.remote,
                "last_commit": self.git.last_commit,
                "last_commit_message": self.git.last_commit_message,
            },
            "docker": {
                "installed": self.docker.installed,
                "running": self.docker.running,
                "compose_files": self.docker.compose_files,
            },
            "runtime": {
                "opencode": self.runtime.opencode,
                "ai_jail": self.runtime.ai_jail,
            },
            "structure": {
                "has_readme": self.structure.has_readme,
                "has_license": self.structure.has_license,
                "has_tests_dir": self.structure.has_tests_dir,
                "has_docs_dir": self.structure.has_docs_dir,
            },
            "skills": self.skills,
            "memory": self.memory.to_dict() if self.memory else {},
            "research": self.research,
            "timestamp": self.timestamp,
        }
