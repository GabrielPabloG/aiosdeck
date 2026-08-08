"""End-to-end quality gates in the workflow pipeline.

Mirrors the WorkflowEngine setup from test_workflow.py but injects a
QualityConfig and deterministic fake gates so the full gate chain
(block / advance / skip / override) can be exercised without network or LLM.
"""

from tests.integration.quality_helpers import (
    FakeGate,
    GATE_ORDER,
    failed,
    make_workflow,
    passed,
    run_workflow,
    setup_project,
    skipped,
)

from aios.quality.contracts import Severity


def _all_passing_gates() -> dict:
    return {name: FakeGate(passed()) for name in GATE_ORDER}


def _release_gates() -> dict:
    gates = _all_passing_gates()
    gates["release_gate"] = FakeGate(skipped())
    return gates


def test_all_gates_passing_succeeds(tmp_path):
    repo = setup_project(tmp_path)
    workflow, scheduler = make_workflow(tmp_path, repo, _all_passing_gates())
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        names = [s.name for s in result.stages]
        assert "code_gate" in names
        assert "security_gate" in names
        assert "test_gate" in names
        assert "documentation_gate" in names
        assert "release_gate" not in names
        code_stage = next(s for s in result.stages if s.name == "code_gate")
        assert code_stage.success is True
        assert code_stage.details["gate"]["status"] == "passed"
    finally:
        scheduler.shutdown()


def test_code_gate_blocks_pipeline(tmp_path):
    repo = setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = FakeGate(failed(Severity.HIGH))
    workflow, scheduler = make_workflow(tmp_path, repo, gates)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is False
        assert [s.name for s in result.stages] == [
            "planner",
            "git",
            "scheduler",
            "developer:1",
            "developer:2",
            "code_gate",
        ]
        assert any("code_gate" in e for e in result.errors)
        code_stage = result.stages[-1]
        assert code_stage.success is False
        assert code_stage.details["policy"]["decision"] == "block"
    finally:
        scheduler.shutdown()


def test_medium_in_dev_warns_and_advances(tmp_path):
    repo = setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = FakeGate(failed(Severity.MEDIUM))
    workflow, scheduler = make_workflow(tmp_path, repo, gates, environment="dev")
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        code_stage = next(s for s in result.stages if s.name == "code_gate")
        assert code_stage.success is True
        assert code_stage.details["policy"]["decision"] == "warn"
    finally:
        scheduler.shutdown()


def test_medium_in_release_blocks(tmp_path):
    repo = setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = FakeGate(failed(Severity.MEDIUM))
    workflow, scheduler = make_workflow(tmp_path, repo, gates, environment="release")
    try:
        result = run_workflow(workflow, repo)
        assert result.success is False
        assert result.stages[-1].name == "code_gate"
        assert result.stages[-1].success is False
    finally:
        scheduler.shutdown()


def test_skipped_gate_advances_with_annotation(tmp_path):
    repo = setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["security_gate"] = FakeGate(skipped())
    workflow, scheduler = make_workflow(tmp_path, repo, gates)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        security_stage = next(s for s in result.stages if s.name == "security_gate")
        assert security_stage.success is True
        assert security_stage.details["skipped"] is True
        assert security_stage.details["gate"]["status"] == "skipped"
    finally:
        scheduler.shutdown()


def test_override_lifts_block_in_dev(tmp_path):
    repo = setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = FakeGate(failed(Severity.HIGH))
    overrides = [{"gate": "code_gate", "environment": "dev", "reason": "manual review ok"}]
    workflow, scheduler = make_workflow(tmp_path, repo, gates, overrides=overrides)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        code_stage = next(s for s in result.stages if s.name == "code_gate")
        assert code_stage.success is True
        assert code_stage.details["policy"]["overridden"] is True
        assert code_stage.details["policy"]["override_reason"] == "manual review ok"
    finally:
        scheduler.shutdown()


def test_release_gate_runs_skipped_in_release_env(tmp_path):
    repo = setup_project(tmp_path)
    workflow, scheduler = make_workflow(tmp_path, repo, _release_gates(), environment="release")
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        names = [s.name for s in result.stages]
        assert "release_gate" in names
        assert names.index("release_gate") > names.index("documentation_gate")
        release_stage = next(s for s in result.stages if s.name == "release_gate")
        assert release_stage.success is True
        assert release_stage.details["skipped"] is True
    finally:
        scheduler.shutdown()


def test_release_gate_not_run_in_dev_env(tmp_path):
    repo = setup_project(tmp_path)
    workflow, scheduler = make_workflow(tmp_path, repo, _release_gates(), environment="dev")
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        assert all(s.name != "release_gate" for s in result.stages)
    finally:
        scheduler.shutdown()


def test_without_quality_config_no_gate_stages(tmp_path):
    repo = setup_project(tmp_path)
    workflow, scheduler = make_workflow(tmp_path, repo, _all_passing_gates(), quality_config=None)
    try:
        result = run_workflow(workflow, repo)
        assert result.success is True
        names = [s.name for s in result.stages]
        assert "code_gate" not in names
        assert "security_gate" not in names
        assert "test_gate" not in names
        assert "documentation_gate" not in names
    finally:
        scheduler.shutdown()
