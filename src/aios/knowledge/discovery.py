"""Source discovery — scans a project directory and produces candidate sources.

Returns a deterministic (sorted) list of SourceCandidate named tuples
with type, path, version, and optional metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("aios.knowledge.discovery")


@dataclass
class SourceCandidate:
    type: str
    path: str
    version: str = "1"
    metadata: dict = field(default_factory=dict)


def discover_sources(project_path: Path) -> list[SourceCandidate]:
    root = project_path.resolve()
    candidates: list[SourceCandidate] = []

    candidates.extend(_discover_skills(root))
    candidates.extend(_discover_adrs(root))
    candidates.extend(_discover_research(root))
    candidates.extend(_discover_documentation(root))
    candidates.extend(_discover_code(root))

    candidates.sort(key=lambda c: (c.type, c.path))
    return candidates


def _discover_skills(root: Path) -> list[SourceCandidate]:
    """Discover skill sources via SkillRegistry (single source of truth).

    Delegates directory walking and frontmatter parsing to SkillRegistry,
    avoiding duplicated filesystem scanning logic. Also discovers nested
    .md files inside skill directories (documentation pages).
    """
    from aios.skills.registry import SkillRegistry

    results: list[SourceCandidate] = []
    registry = SkillRegistry(root)
    for meta in registry.load(include_deprecated=True):
        skill_dir = registry._project_path / ".opencode" / "skills" / meta.name
        stype = "project_dna" if meta.name == "project-dna" else "skill"
        results.append(
            SourceCandidate(
                type=stype,
                path=_rel(root, skill_dir / "SKILL.md"),
                metadata=meta.to_dict(),
            )
        )
        for md_file in sorted(skill_dir.rglob("*.md")):
            if md_file.name == "SKILL.md":
                continue
            results.append(SourceCandidate(type=stype, path=_rel(root, md_file)))
    return results


def _discover_adrs(root: Path) -> list[SourceCandidate]:
    adr_dir = root / "docs" / "decisions"
    if not adr_dir.is_dir():
        return []
    return [SourceCandidate(type="adr", path=_rel(root, f)) for f in sorted(adr_dir.glob("*.md"))]


def _discover_research(root: Path) -> list[SourceCandidate]:
    reports_dir = root / "docs" / "reports"
    if not reports_dir.is_dir():
        return []
    return [
        SourceCandidate(type="research", path=_rel(root, f))
        for f in sorted(reports_dir.glob("*.md"))
    ]


def _discover_documentation(root: Path) -> list[SourceCandidate]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return []
    exclude = {root / "docs" / "decisions", root / "docs" / "reports"}
    results: list[SourceCandidate] = []
    for md_file in sorted(docs_dir.rglob("*.md")):
        if any(parent in exclude for parent in md_file.parents):
            continue
        results.append(
            SourceCandidate(
                type="documentation",
                path=_rel(root, md_file),
            )
        )
    return results


def _discover_code(root: Path) -> list[SourceCandidate]:
    src_dir = root / "src"
    if not src_dir.is_dir():
        return []
    results: list[SourceCandidate] = []
    for py_file in sorted(src_dir.rglob("*.py")):
        parts = py_file.parts
        if "__pycache__" in parts:
            continue
        results.append(
            SourceCandidate(
                type="code",
                path=_rel(root, py_file),
            )
        )
    return results


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path.resolve())
