"""Skill metadata schema — frontmatter parsing and validation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("aios.skills.metadata")

SKILL_SCHEMA_VERSION = "1"

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_VALID_STATUS = frozenset({"active", "deprecated"})
_QUOTED_STRING_RE = re.compile(r'^"(.*)"$|^\'(.*)\'$')


class SkillMetadataError(Exception):
    """Validation error for skill metadata."""


def _strip_quotes(value: str) -> str:
    match = _QUOTED_STRING_RE.match(value)
    if match:
        return (match.group(1) or match.group(2) or value).strip()
    return value.strip()


def _raw_value(raw: str) -> str:
    return _strip_quotes(raw.strip())


def parse_frontmatter(text: str) -> dict:
    """Parse YAML-like frontmatter between ``---`` delimiters.

    Handles scalars (key: value) and block lists (key:\\n  - item).
    This is deliberately a minimal subset — no nested maps, inline
    lists, anchors, or flow style. It covers the exact schema we own.
    """
    if not text.startswith("---"):
        return {}

    end = text.find("---", 3)
    if end == -1:
        return {}
    block = text[3:end]

    result: dict[str, object] = {}
    key_stack: list[str] = []

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        if ":" in line:
            colon = line.index(":")
            key = line[:colon].strip()
            rest = line[colon + 1 :].strip()

            if not rest or rest == "|":
                key_stack = [key]
                continue

            if key.startswith("- "):
                continue

            list_line_match = re.match(r"^\s*-\s+(.+)", rest)
            if list_line_match:
                if key:  # key: followed by list start on same line
                    result[key] = [_raw_value(list_line_match.group(1))]
                    key_stack = [key]
                continue

            result[key] = _raw_value(rest)
            key_stack = [key]
        elif line.strip().startswith("- "):
            list_value = line.strip()[2:].strip()
            if key_stack:
                key = key_stack[0]
                existing = result.get(key)
                if isinstance(existing, list):
                    existing.append(_raw_value(list_value))
                else:
                    result[key] = [_raw_value(list_value)]

    return result


@dataclass
class SkillMetadata:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0
    version: str = "1"
    owner: str = ""
    updated_at: str = ""
    status: str = "active"
    schema_version: str = SKILL_SCHEMA_VERSION

    def validate(self) -> SkillMetadata:
        if not self.name:
            raise SkillMetadataError("Skill name is required")
        if not _NAME_RE.match(self.name):
            raise SkillMetadataError(
                f"Skill name must be a lowercase slug (a-z, 0-9, hyphens): {self.name!r}"
            )
        if not self.description:
            raise SkillMetadataError(f"Skill '{self.name}': description is required")
        if self.status not in _VALID_STATUS:
            raise SkillMetadataError(
                f"Skill '{self.name}': status must be one of {sorted(_VALID_STATUS)}, "
                f"got {self.status!r}"
            )
        if not isinstance(self.priority, int) or self.priority < 0:
            raise SkillMetadataError(
                f"Skill '{self.name}': priority must be a non-negative integer, "
                f"got {self.priority!r}"
            )
        for i, t in enumerate(self.triggers):
            if not t or not t.strip():
                raise SkillMetadataError(
                    f"Skill '{self.name}': trigger at index {i} must be a non-empty string"
                )
        for i, s in enumerate(self.scope):
            if not s or not s.strip():
                raise SkillMetadataError(
                    f"Skill '{self.name}': scope at index {i} must be a non-empty string"
                )
        for i, d in enumerate(self.dependencies):
            if not d or not d.strip():
                raise SkillMetadataError(
                    f"Skill '{self.name}': dependency at index {i} must be a non-empty string"
                )
        if self.schema_version != SKILL_SCHEMA_VERSION:
            raise SkillMetadataError(
                f"Skill '{self.name}': unsupported schema version {self.schema_version!r}, "
                f"expected {SKILL_SCHEMA_VERSION!r}"
            )
        return self

    @classmethod
    def from_frontmatter(cls, text: str) -> SkillMetadata:
        data = parse_frontmatter(text)
        name = data.get("name", "")
        description = data.get("description", "")

        if not name:
            raise SkillMetadataError("Skill metadata missing required field 'name'")

        return cls(
            name=str(name),
            description=str(description),
            triggers=_as_str_list(data.get("triggers", [])),
            scope=_as_str_list(data.get("scope", [])),
            dependencies=_as_str_list(data.get("dependencies", [])),
            priority=_coerce_int(data.get("priority", 0)),
            version=str(data.get("version", "1")),
            owner=str(data.get("owner", "")),
            updated_at=str(data.get("updated_at", "")),
            status=str(data.get("status", "active")),
            schema_version=str(data.get("schema_version", SKILL_SCHEMA_VERSION)),
        ).validate()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "scope": list(self.scope),
            "dependencies": list(self.dependencies),
            "priority": self.priority,
            "version": self.version,
            "owner": self.owner,
            "updated_at": self.updated_at,
            "status": self.status,
            "schema_version": self.schema_version,
        }


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _coerce_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
