"""DocumentationGate — deterministic check that docs reflect the change.

A deterministic skeleton: the CHANGELOG must carry an entry for the current
change (``Unreleased`` or today's date) and TODO.md must not hold blockers.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from aios.quality.contracts import (
    GateFinding,
    GateInput,
    GateResult,
    GateStatus,
    Severity,
)
from aios.quality.gates.common import read_text

_CHANGELOG_NAMES = ("CHANGELOG.md", "CHANGELOG", "changelog.md")
_TODO_NAMES = ("TODO.md", "TODO")
_BLOCKER_RE = re.compile(r"(?i)\bblock\w*\b")


def _find(base: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = base / name
        if path.exists():
            return path
    return None


class DocumentationGate:
    name = "documentation_gate"

    def is_applicable(self, gate_input: GateInput) -> bool:
        base = gate_input.project_path or Path.cwd()
        return _find(base, _CHANGELOG_NAMES) is not None or _find(base, _TODO_NAMES) is not None

    async def run(self, gate_input: GateInput) -> GateResult:
        if not self.is_applicable(gate_input):
            return GateResult(status=GateStatus.SKIPPED, reason="no documentation to verify")
        base = gate_input.project_path or Path.cwd()
        findings = []
        changelog = _find(base, _CHANGELOG_NAMES)
        if changelog is not None:
            text = await read_text(changelog)
            today = datetime.now(UTC).date().isoformat()
            if "Unreleased" not in text and today not in text:
                findings.append(
                    GateFinding(
                        id="changelog-missing-entry",
                        title="CHANGELOG has no entry for this change",
                        severity=Severity.HIGH,
                        category="documentation",
                        evidence=str(changelog),
                    )
                )
        todo = _find(base, _TODO_NAMES)
        if todo is not None:
            text = await read_text(todo)
            if _BLOCKER_RE.search(text):
                findings.append(
                    GateFinding(
                        id="todo-blockers",
                        title="TODO.md contains blocking items",
                        severity=Severity.MEDIUM,
                        category="documentation",
                        evidence=str(todo),
                    )
                )
        if not findings:
            return GateResult(status=GateStatus.PASSED, reason="documentation reflects changes")
        return GateResult(
            status=GateStatus.FAILED,
            reason=f"{len(findings)} documentation finding(s)",
            findings=findings,
        )
