"""Task — unit of work assigned to an agent."""

from dataclasses import dataclass, field


@dataclass
class Task:
    description: str = ""
    task_type: str = "code"
    files: list[str] = field(default_factory=list)
