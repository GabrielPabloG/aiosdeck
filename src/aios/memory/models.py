"""Memory data models — domain, not database."""

from dataclasses import dataclass, field


class StorageError(Exception):
    """Domain error for storage failures. Hides SQLite from callers."""


@dataclass
class Convention:
    id: int | None = None
    category: str = ""
    rule: str = ""
    source: str = ""
    project_id: str = ""
    created_at: str = ""
    last_seen: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "rule": self.rule,
            "source": self.source,
        }


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

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "context": self.context,
            "decision": self.decision,
            "status": self.status,
        }


@dataclass
class Pattern:
    id: int | None = None
    name: str = ""
    description: str = ""
    usage_count: int = 0
    project_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "usage_count": self.usage_count,
        }


@dataclass
class Mistake:
    id: int | None = None
    description: str = ""
    category: str = ""
    severity: str = "warning"
    project_id: str = ""
    resolved_at: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
        }


@dataclass
class ProjectKnowledge:
    conventions: list[Convention] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    patterns: list[Pattern] = field(default_factory=list)
    mistakes: list[Mistake] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([self.conventions, self.decisions, self.patterns, self.mistakes])

    def to_dict(self) -> dict:
        return {
            "conventions": [c.to_dict() for c in self.conventions],
            "decisions": [d.to_dict() for d in self.decisions],
            "patterns": [p.to_dict() for p in self.patterns],
            "mistakes": [m.to_dict() for m in self.mistakes],
        }
