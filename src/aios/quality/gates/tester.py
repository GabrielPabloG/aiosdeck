"""TestGate — wraps the TesterAgent structured report.

A test run is green when ``failed == 0``. The gate is deterministic and needs
no network or LLM: it only inspects the report dict produced by TesterAgent.
"""

from __future__ import annotations

from aios.quality.contracts import (
    GateFinding,
    GateInput,
    GateResult,
    GateStatus,
    Severity,
)


class TestGate:
    name = "test_gate"

    def is_applicable(self, gate_input: GateInput) -> bool:
        return gate_input.test_report is not None

    async def run(self, gate_input: GateInput) -> GateResult:
        if not self.is_applicable(gate_input):
            return GateResult(status=GateStatus.SKIPPED, reason="no test report")
        report = gate_input.test_report or {}
        if report.get("status") == "error":
            errors = report.get("errors") or []
            findings = [
                GateFinding(
                    id=f"test-error-{index}",
                    title=str(error),
                    severity=Severity.HIGH,
                    category="test-error",
                    evidence=str(error),
                )
                for index, error in enumerate(errors)
            ]
            return GateResult(
                status=GateStatus.ERROR,
                reason="test run errored",
                findings=findings,
            )
        failed = report.get("failed", 0)
        passed = report.get("passed", 0)
        if failed == 0:
            return GateResult(
                status=GateStatus.PASSED,
                reason=f"{passed} test(s) passed",
                metadata={
                    "passed": passed,
                    "collected": report.get("collected", 0),
                },
            )
        return GateResult(
            status=GateStatus.FAILED,
            reason=f"{failed} test(s) failed",
            findings=[
                GateFinding(
                    id="test-failures",
                    title=f"{failed} test(s) failed",
                    severity=Severity.HIGH,
                    category="test-failure",
                    evidence=str(failed),
                )
            ],
        )
