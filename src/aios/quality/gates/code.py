"""CodeGate — lint and format gate powered by ruff.

Runs ``ruff check`` and ``ruff format --check`` over the project, following
the subprocess pattern established by ``TesterAgent._run``. The gate is
deterministic: same project, same ruff version, same result.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from aios.quality.contracts import (
    GateFinding,
    GateInput,
    GateResult,
    GateStatus,
    Severity,
)
from aios.quality.gates.common import python_files, run_cmd

_LINT_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<code>[A-Z]{1,3}\d+)(?: \[[^\]]+\])? (?P<msg>.*)$"
)
_REFORMAT_RE = re.compile(r"(?i)^would reformat:")


def _severity_for_rule(code: str) -> Severity:
    """Pyflakes ``F*`` rules are real errors; the rest are style issues."""
    return Severity.HIGH if code.startswith("F") else Severity.MEDIUM


def _parse_ruff_check(output: str) -> list[GateFinding]:
    findings = []
    for line in output.splitlines():
        match = _LINT_LINE_RE.match(line)
        if not match:
            continue
        code = match.group("code")
        findings.append(
            GateFinding(
                id=code,
                title=match.group("msg").strip() or code,
                severity=_severity_for_rule(code),
                detail=line,
                category="lint",
                evidence=f"{match.group('path')}:{match.group('line')}",
            )
        )
    return findings


def _parse_ruff_format(output: str) -> list[GateFinding]:
    findings = []
    for line in output.splitlines():
        if not _REFORMAT_RE.match(line):
            continue
        _, _, evidence = line.partition(":")
        findings.append(
            GateFinding(
                id="RUF-FMT",
                title="file would be reformatted by ruff format",
                severity=Severity.MEDIUM,
                detail=line,
                category="format",
                evidence=evidence.strip() or line,
            )
        )
    return findings


class CodeGate:
    name = "code_gate"

    def __init__(self, python: str | None = None) -> None:
        self._python = python or sys.executable

    def is_applicable(self, gate_input: GateInput) -> bool:
        return bool(python_files(gate_input))

    async def run(self, gate_input: GateInput) -> GateResult:
        if not self.is_applicable(gate_input):
            return GateResult(status=GateStatus.SKIPPED, reason="no python files to check")
        target = str(gate_input.project_path or Path.cwd())
        try:
            check_rc, check_out = await run_cmd(
                [self._python, "-m", "ruff", "check", "--output-format", "concise", target]
            )
            fmt_rc, fmt_out = await run_cmd(
                [self._python, "-m", "ruff", "format", "--check", target]
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return GateResult(status=GateStatus.ERROR, reason=f"cannot run ruff: {exc}")
        if check_rc != 0 and "No module named" in check_out:
            return GateResult(status=GateStatus.ERROR, reason="ruff is not installed")
        findings = _parse_ruff_check(check_out) + _parse_ruff_format(fmt_out)
        if check_rc == 0 and fmt_rc == 0:
            return GateResult(
                status=GateStatus.PASSED,
                reason="ruff check and format clean",
                metadata={"lint_issues": len(_parse_ruff_check(check_out))},
            )
        return GateResult(
            status=GateStatus.FAILED,
            reason=f"{len(findings)} lint/format issue(s)",
            findings=findings,
        )
