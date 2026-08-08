"""SecurityGate — deterministic secret and unsafe-construct scan.

Reuses the pure detectors from ``aios.agents.detectors`` (``scan_secrets`` /
``scan_unsafe``) and maps their ``info`` / ``warning`` / ``error`` severities
to the canonical vocabulary via ``severity_mapper``.
"""

from __future__ import annotations

from pathlib import Path

from aios.agents.detectors import scan_secrets, scan_unsafe
from aios.quality.contracts import GateInput, GateResult, GateStatus
from aios.quality.gates.common import python_files, read_text, reviewer_finding


class SecurityGate:
    name = "security_gate"

    def is_applicable(self, gate_input: GateInput) -> bool:
        return bool(python_files(gate_input))

    async def run(self, gate_input: GateInput) -> GateResult:
        if not self.is_applicable(gate_input):
            return GateResult(status=GateStatus.SKIPPED, reason="no files to scan")
        base = gate_input.project_path or Path.cwd()
        findings = []
        for rel in python_files(gate_input):
            text = await read_text(base / rel)
            findings.extend(reviewer_finding(item, "security") for item in scan_secrets(text, rel))
            findings.extend(reviewer_finding(item, "security") for item in scan_unsafe(text, rel))
        if not findings:
            return GateResult(status=GateStatus.PASSED, reason="no security findings")
        return GateResult(
            status=GateStatus.FAILED,
            reason=f"{len(findings)} security finding(s)",
            findings=findings,
        )
