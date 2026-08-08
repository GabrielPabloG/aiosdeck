"""Source discovery — scans a project directory and produces candidate sources.

Returns a deterministic (sorted) list of SourceCandidate named tuples
with type, path, and version.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SourceCandidate:
    type: str
    path: str
    version: str = "1"


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
    skills_dir = root / ".opencode" / "skills"
    if not skills_dir.is_dir():
        return []
    results: list[SourceCandidate] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            stype = "project_dna" if entry.name == "project-dna" else "skill"
            results.append(
                SourceCandidate(
                    type=stype,
                    path=_rel(root, skill_file),
                )
            )
        for md_file in sorted(entry.rglob("*.md")):
            if md_file == skill_file or md_file.parent == entry:
                continue
            results.append(
                SourceCandidate(
                    type=stype,
                    path=_rel(root, md_file),
                )
            )
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
