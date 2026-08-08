"""Skill Registry — loads validated SkillMetadata from filesystem."""

from __future__ import annotations

import logging
from pathlib import Path

from aios.skills.metadata import SkillMetadata, SkillMetadataError

logger = logging.getLogger("aios.skills.registry")


class SkillRegistry:
    def __init__(self, project_path: str | Path) -> None:
        self._project_path = Path(project_path).resolve()
        self._skills: dict[str, SkillMetadata] = {}

    def load(self, *, include_deprecated: bool = False) -> list[SkillMetadata]:
        self._skills.clear()
        skills_dir = self._project_path / ".opencode" / "skills"
        if not skills_dir.is_dir():
            return []

        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8", errors="replace")
                metadata = SkillMetadata.from_frontmatter(text)
                if not include_deprecated and metadata.status == "deprecated":
                    logger.debug("Skipping deprecated skill: %s", metadata.name)
                    continue
                self._skills[metadata.name] = metadata
            except SkillMetadataError as exc:
                logger.warning("Invalid skill %s: %s", entry.name, exc)
            except OSError as exc:
                logger.warning("Cannot read skill %s: %s", entry.name, exc)

        return list(self._skills.values())

    @property
    def skills(self) -> list[SkillMetadata]:
        if not self._skills:
            return self.load()
        return list(self._skills.values())

    def get(self, name: str) -> SkillMetadata | None:
        if not self._skills:
            self.load()
        return self._skills.get(name)
