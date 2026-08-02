"""Memory Engine — domain-oriented knowledge persistence.

SQLite is an implementation detail. This is the public abstraction.

Storage priority:
1. AIOS_MEMORY_PATH (env — no silent fallback)
2. ./.aios/memory.db (project-scoped, default)
3. ~/.local/share/aiosdeck/memory.db (global fallback)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from aios.memory.models import ProjectKnowledge, StorageError
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
        try:
            self._store = SQLiteStore(self._db_path, self._project_id)
            self._store.open()
        except StorageError as exc:
            self._store = None
            raise RuntimeError(str(exc)) from exc

    def health_check(self) -> bool:
        if self._store is None:
            return True  # not initialized, not a failure
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

    def enrich_context(self, context: ContextPacket) -> None:
        context.memory = self.recall()

    def _resolve_db_path(self, override: str | None) -> Path:
        if override:
            return Path(override)

        env = os.environ.get("AIOS_MEMORY_PATH")
        if env is not None:
            return Path(env)

        project_db = self._project_path / ".aios" / "memory.db"
        return project_db

    def is_available(self) -> bool:
        """Check if the db path is writable."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            return os.access(self._db_path.parent, os.W_OK)
        except OSError:
            return False
