"""Contract tests for the WorkflowStage ↔ StageSummary mapper boundary.

The `stage_to_summary()` function in `core/run_result.py` normalizes a
pipeline stage (duck-typed: name + success + error + details) into the
CLI-consumed `StageSummary`. This boundary must stay bidirectional and
deterministic — any change to the mapping rules requires a conscious update
here.

Ownership boundary: Workflow (workflow/models.py) → Core (core/run_result.py).
"""

from aios.core.run_result import RunResult, StageSummary, stage_to_summary
from aios.workflow.models import WorkflowStage


def test_mapper_accepts_workflowstage():
    """The mapper accepts a standard WorkflowStage."""
    stage = WorkflowStage(name="planner", success=True)
    summary = stage_to_summary(stage)
    assert isinstance(summary, StageSummary)
    assert summary.name == "planner"
    assert summary.status == "success"
    assert summary.reason is None


def test_mapper_accepts_duck_typed_object():
    """The mapper works with any duck-typed object having name + success."""

    class DuckStage:
        name = "custom"
        success = True
        details = {}

    summary = stage_to_summary(DuckStage())
    assert summary.name == "custom"
    assert summary.status == "success"


def test_mapper_maps_success_to_status():
    """success=True → status='success'."""
    for name in ("planner", "developer", "reviewer", "tester", "documentation", "git"):
        stage = WorkflowStage(name=name, success=True)
        summary = stage_to_summary(stage)
        assert summary.status == "success", f"expected success for {name}"


def test_mapper_maps_failure_to_status():
    """success=False → status='failed' with reason from error."""
    stage = WorkflowStage(name="tester", success=False, error="test failure")
    summary = stage_to_summary(stage)
    assert summary.status == "failed"
    assert summary.reason == "test failure"


def test_mapper_maps_skipped_to_status():
    """details.skipped=True → status='skipped' regardless of success."""
    stage = WorkflowStage(name="documentation", success=False, details={"skipped": True})
    summary = stage_to_summary(stage)
    assert summary.status == "skipped"


def test_mapper_skip_overrides_failure():
    """Skipped takes precedence over failure."""
    stage = WorkflowStage(name="git", success=False, error="push denied", details={"skipped": True})
    summary = stage_to_summary(stage)
    assert summary.status == "skipped"
    # Reason is not set when skipped
    assert summary.reason is None


def test_mapper_no_error_field_graceful():
    """Missing error field → reason is None."""

    class NoErrorStage:
        name = "planner"
        success = False

    summary = stage_to_summary(NoErrorStage())
    assert summary.status == "failed"
    assert summary.reason is None


def test_mapper_preserves_details():
    """Original details dictionary is passed through."""
    details = {"duration_ms": 1234.5, "model": "gpt-4o"}
    stage = WorkflowStage(name="developer", success=True, details=details)
    summary = stage_to_summary(stage)
    assert summary.details == details


def test_mapper_round_trip_determinism():
    """The same stage always maps to the same summary."""
    stage = WorkflowStage(name="planner", success=True, details={"count": 42})
    a = stage_to_summary(stage)
    b = stage_to_summary(stage)
    assert (a.name, a.status, a.reason, a.details) == (b.name, b.status, b.reason, b.details)


def test_mapper_is_idempotent():
    """Re-mapping a summary preserves the status."""
    stage = WorkflowStage(name="reviewer", success=True)
    summary = stage_to_summary(stage)
    assert summary.status == "success"
    # Re-mapping the same stage produces identical output
    summary2 = stage_to_summary(stage)
    assert summary == summary2


def test_runresult_from_workflow_calls_mapper():
    """RunResult.from_workflow() invokes stage_to_summary for every stage."""
    from aios.workflow.models import WorkflowResult

    stages = (
        WorkflowStage(name="planner", success=True),
        WorkflowStage(name="developer", success=True),
        WorkflowStage(name="tester", success=False, error="assertion"),
    )
    wr = WorkflowResult(
        run_id=1,
        goal="test",
        branch=None,
        success=False,
        plan={},
        stages=stages,
        subtask_count=2,
        completed_count=1,
        errors=("assertion",),
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
    )
    rr = RunResult.from_workflow(wr)
    assert len(rr.stages) == 3
    assert rr.stages[0].status == "success"
    assert rr.stages[2].status == "failed"
    assert rr.stages[2].reason == "assertion"
