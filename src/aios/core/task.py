"""Task — unit of work assigned to an agent."""

from dataclasses import dataclass, field


@dataclass
class Task:
    """Unit of work assigned to an agent.  The description carries the human
    intent; ``task_type`` and ``files`` provide routing hints."""

    description: str = ""
    task_type: str = "code"
    files: list[str] = field(default_factory=list)
