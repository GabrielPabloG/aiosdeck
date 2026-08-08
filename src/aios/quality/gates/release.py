"""ReleaseGate — skeleton, never applies in the current pipeline.

Kept as a placeholder for a future release-time gate; skipped by default.
"""

from __future__ import annotations

from aios.quality.contracts import GateInput, GateResult, GateStatus


class ReleaseGate:
    name = "release_gate"

    def is_applicable(self, gate_input: GateInput) -> bool:
        return False

    async def run(self, gate_input: GateInput) -> GateResult:
        return GateResult(status=GateStatus.SKIPPED, reason="release gate not implemented")
