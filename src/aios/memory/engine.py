"""Memory Engine — domain-oriented knowledge persistence.

SQLite is an implementation detail. This is the public abstraction.
"""

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from aios.memory.models import ProjectKnowledge
from aios.memory.store import SQLiteStore

if TYPE_CHECKING:
    from aios.context.packet import ContextPacket

logger = logging.getLogger("aios.memory")


class MemoryEngine:
    name = "memory"

    def __init__(self, project_path: Path | None = None, db_path: str | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = self._resolve_db_path(db_path)
        self._store: SQLiteStore | None = None

    def initialize(self) -> None:
        self._store = SQLiteStore(self._db_path, self._project_id)
        self._store.open()

    def health_check(self) -> bool:
        if self._store is None:
            return True  # not initialized yet, not a failure
        return self._store.is_open()

    def shutdown(self) -> None:
        if self._store:
            self._store.close()
            self._store = None

    def recall(self) -> ProjectKnowledge:
        if self._store is None:
            return ProjectKnowledge()
        return ProjectKnowledge(
            conventions=self._store.get_conventions(),
            decisions=self._store.get_decisions(status="active"),
            patterns=self._store.get_patterns(),
            mistakes=self._store.get_mistakes(resolved=False),
        )

    def remember_convention(self, rule: str, category: str = "", source: str = "") -> None:
        if self._store is None:
            return
        self._store.upsert_convention(rule, category, source)

    def remember_decision(
        self, title: str, context: str = "", decision: str = "", consequences: str = ""
    ) -> None:
        if self._store is None:
            return
        self._store.add_decision(title, context, decision, consequences)

    def remember_pattern(self, name: str, description: str = "") -> None:
        if self._store is None:
            return
        self._store.add_pattern(name, description)

    def remember_mistake(
        self, description: str, category: str = "", severity: str = "warning"
    ) -> None:
        if self._store is None:
            return
        self._store.add_mistake(description, category, severity)

    def enrich_context(self, context: "ContextPacket") -> None:
        knowledge = self.recall()
        context.memory = {
            "conventions": [c.rule for c in knowledge.conventions],
            "decisions": [d.title for d in knowledge.decisions],
            "patterns": [p.name for p in knowledge.patterns],
            "mistakes": [m.description for m in knowledge.mistakes],
        }

    def _resolve_db_path(self, override: str | None) -> Path:
        if override:
            return Path(override)
        env = os.environ.get("AIOS_MEMORY_PATH")
        if env:
            return Path(env)
        return Path.home() / ".local" / "share" / "aiosdeck" / "memory.db"
