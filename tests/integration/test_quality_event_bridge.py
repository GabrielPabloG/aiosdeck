"""Event bridge e2e: workflow emits quality.* events → bus → telemetry store.

Safety properties under test:
- with quality config active, gate runs land in telemetry_gates
- without quality config, zero quality events are emitted
- a failing subscriber never crashes the workflow (bus isolates handlers)
"""

from aios.events.bus import EventBus
from aios.telemetry.engine import TelemetryEngine
from tests.integration.quality_helpers import (
    FakeGate,
    GATE_ORDER,
    failed,
    make_workflow,
    passed,
    run_workflow,
    setup_project,
)

from aios.quality.contracts import Severity


def _telemetry(tmp_path, bus):
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(tmp_path / "telemetry.db"))
    engine.set_event_bus(bus)
    engine.initialize()
    return engine


def _all_passing_gates() -> dict:
    return {name: FakeGate(passed()) for name in GATE_ORDER}


def test_bridge_populates_gate_telemetry(tmp_path):
    repo = setup_project(tmp_path)
    bus = EventBus()
    telemetry = _telemetry(tmp_path, bus)
    telemetry.set_event_bus(bus)
    workflow, scheduler = make_workflow(tmp_path, repo, _all_passing_gates(), bus=bus)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        rows = telemetry.query_gate_records()
        gates = [r["gate"] for r in rows]
        assert "code_gate" in gates
        assert "security_gate" in gates
        assert "test_gate" in gates
        assert "documentation_gate" in gates
        passed_rows = [r for r in rows if r["gate"] == "code_gate"]
        assert passed_rows[0]["status"] == "passed"
        assert passed_rows[0]["blocked"] == 0
    finally:
        scheduler.shutdown()
        telemetry.shutdown()


def test_bridge_blocked_gate_recorded(tmp_path):
    repo = setup_project(tmp_path)
    bus = EventBus()
    telemetry = _telemetry(tmp_path, bus)
    telemetry.set_event_bus(bus)
    gates = _all_passing_gates()
    gates["code_gate"] = FakeGate(failed(Severity.HIGH))
    workflow, scheduler = make_workflow(tmp_path, repo, gates, bus=bus)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is False
        rows = telemetry.query_gate_records(gate="code_gate")
        assert rows[0]["status"] == "failed"
        assert rows[0]["blocked"] == 1
        assert rows[0]["findings_high"] == 1
    finally:
        scheduler.shutdown()
        telemetry.shutdown()


def test_bridge_zero_events_without_quality_config(tmp_path):
    repo = setup_project(tmp_path)
    bus = EventBus()
    telemetry = _telemetry(tmp_path, bus)
    telemetry.set_event_bus(bus)
    workflow, scheduler = make_workflow(
        tmp_path, repo, _all_passing_gates(), quality_config=None, bus=bus
    )
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        assert telemetry.query_gate_records() == []
    finally:
        scheduler.shutdown()
        telemetry.shutdown()


def test_failing_subscriber_never_crashes_workflow(tmp_path):
    repo = setup_project(tmp_path)
    bus = EventBus()

    def boom(event):
        raise RuntimeError("subscriber exploded")

    bus.subscribe("quality.gate_started", boom)
    bus.subscribe("quality.started", boom)
    workflow, scheduler = make_workflow(tmp_path, repo, _all_passing_gates(), bus=bus)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        assert [s.name for s in result.stages if s.name.endswith("_gate")]
    finally:
        scheduler.shutdown()
