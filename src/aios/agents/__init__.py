"""Agent protocol, result, and task definitions."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Task:
    description: str = ""
    task_type: str = "code"
    files: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    success: bool = True
    output: str = ""
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class Agent(Protocol):
    name: str
    required_capabilities: list[str]
    required_skills: list[str]

    def execute(self, task: Task, context) -> AgentResult: ...
