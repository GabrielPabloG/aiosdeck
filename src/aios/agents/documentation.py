"""DocumentationAgent — generates changelog fragments from structured reports.

Responsibilities:
- Generate changelog fragments from structured reports.
- Write files only under docs/ by default.

Executor-free by design: the AgentExecutor invokes ``execute()``; the
deterministic generator lives behind the private ``_generate_changelog_fragment()``.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aios.agents.base import BaseAgent
from aios.agents.contracts import (
    RUNTIME_ERROR,
    STATE_FAILED,
    AgentError,
    coerce_task,
)
from aios.agents.models import AgentResult


@dataclass
class ChangelogFragment:
    path: Path
    written: bool
    preview: str


class DocumentationAgent(BaseAgent):
    name = "documentation"
    timeout = 30.0
    required_capabilities = ["filesystem_read", "filesystem_write"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, docs_dir: str | None = None) -> None:
        super().__init__()
        self._docs_dir = Path(docs_dir) if docs_dir else Path("docs")

    def execute(self, task, context) -> AgentResult:
        """Contract method — report and dry_run arrive via the AgentTask params."""
        agent_task = coerce_task(task)
        report = agent_task.params.get("report")
        if not isinstance(report, Mapping):
            return AgentResult(
                success=False,
                errors=["report is required"],
                error=AgentError(code=RUNTIME_ERROR, message="report is required"),
                error_code=RUNTIME_ERROR,
                status=STATE_FAILED,
                agent=self.name,
                task_id=agent_task.task_id,
                correlation_id=agent_task.correlation_id,
            )
        dry_run = agent_task.params.get("dry_run", True)
        fragment = self._generate_changelog_fragment(report, dry_run=dry_run)
        payload = {
            "path": str(fragment.path),
            "written": fragment.written,
            "preview": fragment.preview,
        }
        return AgentResult(
            success=True,
            output=json.dumps(payload, indent=2),
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )

    def _generate_changelog_fragment(
        self,
        report: Mapping[str, Any],
        dry_run: bool = True,
    ) -> ChangelogFragment:
        """Generate a changelog fragment from a structured report (internal API).

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
