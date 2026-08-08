"""Architectural contract tests for the Quality Gate subsystem.

These tests freeze the public vocabulary exchanged between the quality
pipeline and the workflow engine:
- canonical ``GateStatus`` / ``Severity`` enums
- structured ``GateResult`` / ``GateFinding`` (never loose text)
- JSON round-trip via ``GateResult.to_dict()``
- every concrete gate satisfies the ``QualityGate`` protocol
"""

import json
from dataclasses import asdict

from aios.quality import (
    CodeGate,
    DocumentationGate,
    ReleaseGate,
    SecurityGate,
    TestGate,
)
from aios.quality.contracts import (
    GateFinding,
    GateInput,
    GateResult,
    GateStatus,
    QualityGate,
    Severity,
)


def test_gate_status_members_are_canonical():
    assert [s.value for s in GateStatus] == ["passed", "failed", "skipped", "error"]


def test_severity_members_are_canonical():
    assert [s.value for s in Severity] == ["low", "medium", "high", "critical"]


def test_gate_result_is_never_free_text():
    result = GateResult(
        status=GateStatus.FAILED,
        reason="lint found issues",
        findings=[GateFinding(id="F401", title="unused import", severity=Severity.HIGH)],
    )
    assert isinstance(result.status, GateStatus)
    assert all(isinstance(f, GateFinding) for f in result.findings)
    assert result.to_dict()["status"] == "failed"


def test_gate_result_to_dict_round_trip():
    result = GateResult(
        status=GateStatus.PASSED,
        reason="ruff clean",
        findings=[
            GateFinding(id="E501", title="long line", severity=Severity.LOW, category="lint")
        ],
        metadata={"elapsed_ms": 12},
    )
    data = result.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["findings"][0]["severity"] == "low"
    assert data["metadata"] == {"elapsed_ms": 12}


def test_gate_finding_to_dict_exposes_evidence():
    finding = GateFinding(
        id="hardcoded-secret",
        title="Potential hardcoded secret",
        detail="app.py:3",
        severity=Severity.HIGH,
        category="security",
        evidence="password = 'x'",
    )
    data = finding.to_dict()
    assert data["severity"] == "high"
    assert data["evidence"] == "password = 'x'"


def test_gate_input_is_structured_not_loose():
    gate_input = GateInput(environment="release")
    assert gate_input.files == []
    assert gate_input.test_report is None
    assert isinstance(asdict(gate_input), dict)


def test_quality_gate_protocol_shape():
    assert hasattr(QualityGate, "run")
    assert hasattr(QualityGate, "is_applicable")


def test_concrete_gates_satisfy_protocol():
    for gate in (CodeGate(), TestGate(), SecurityGate(), DocumentationGate(), ReleaseGate()):
        assert isinstance(gate, QualityGate)
