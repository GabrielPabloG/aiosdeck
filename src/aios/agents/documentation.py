"""Minimal DocumentationAgent scaffold.

Responsibilities:
- Generate changelog fragments or ADR templates from structured reports.
- Write files only under docs/ by default.

ADR template generation is planned future work and is not part of the
current public API.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aios.agents.base import BaseAgent


@dataclass
class ChangelogFragment:
    path: Path
    written: bool
    preview: str


class DocumentationAgent(BaseAgent):
    name = "documentation"
    required_capabilities = ["filesystem_read", "filesystem_write"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, docs_dir: str | None = None) -> None:
        self._docs_dir = Path(docs_dir) if docs_dir else Path("docs")

    def generate_changelog_fragment(
        self,
        report: Mapping[str, Any],
        dry_run: bool = True,
    ) -> ChangelogFragment:
        """Generate a changelog fragment from a structured report.

        Args:
            report: Structured report with a "summary" mapping and an
                "items" sequence of {"severity", "file", "line", "message"}.
            dry_run: When True, the fragment is returned as a preview and
                nothing is written to disk.

        Returns:
            ChangelogFragment with the target path, whether it was written,
            and the fragment content (identical in both modes).
        """
        preview = _build_fragment(report)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self._docs_dir / f"changelog-fragment-{timestamp}.md"

        if dry_run:
            return ChangelogFragment(path=path, written=False, preview=preview)

        self._docs_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(preview, encoding="utf-8")
        return ChangelogFragment(path=path, written=True, preview=preview)


def _build_fragment(report: Mapping[str, Any]) -> str:
    lines = ["# Changelog Fragment", "", "## Summary", ""]
    for key, value in report.get("summary", {}).items():
        lines.append(f"- {key}: {value}")

    items = report.get("items", [])
    if items:
        lines.extend(["", "## Items", ""])
        for item in items:
            severity = item.get("severity", "info")
            location = item.get("file", "unknown")
            if item.get("line"):
                location = f"{location}:{item['line']}"
            lines.append(f"- **{severity}** `{location}` — {item.get('message', '')}")

    return "\n".join(lines).rstrip() + "\n"
