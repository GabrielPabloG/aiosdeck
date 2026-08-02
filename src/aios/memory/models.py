"""Memory data models — domain, not database."""

from dataclasses import dataclass, field


@dataclass
class Convention:
    id: int | None = None
    category: str = ""
    rule: str = ""
    source: str = ""
    project_id: str = ""
    created_at: str = ""
    last_seen: str = ""


@dataclass
class Decision:
    id: int | None = None
    title: str = ""
    context: str = ""
    decision: str = ""
    consequences: str = ""
    status: str = "active"
    project_id: str = ""
    created_at: str = ""


@dataclass
class Pattern:
    id: int | None = None
    name: str = ""
    description: str = ""
    usage_count: int = 0
    project_id: str = ""
    created_at: str = ""


@dataclass
class Mistake:
    id: int | None = None
    description: str = ""
    category: str = ""
    severity: str = "warning"
    project_id: str = ""
    resolved_at: str | None = None
    created_at: str = ""


@dataclass
class ProjectKnowledge:
    conventions: list[Convention] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    patterns: list[Pattern] = field(default_factory=list)
    mistakes: list[Mistake] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([self.conventions, self.decisions, self.patterns, self.mistakes])
