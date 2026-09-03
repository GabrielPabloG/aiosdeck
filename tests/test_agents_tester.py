"""Tests for TesterAgent — dry-run collection and structured report."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from aios.agents.contracts import RUNTIME_ERROR, AgentTask
from aios.agents.tester import TesterAgent

FIXTURE = Path(__file__).parent / "fixtures" / "test_project"


def _agent() -> TesterAgent:
    return TesterAgent()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(FIXTURE / "test_sample.py", project / "test_sample.py")
    return project


def test_tester_capabilities():
    assert "shell" in TesterAgent.required_capabilities
    assert "filesystem_read" in TesterAgent.required_capabilities


def test_tester_dry_run(tmp_path):
    report = _agent()._run(_project(tmp_path), dry_run=True)
    assert report["dry_run"] is True
    assert report["status"] == "ok"
    assert report["collected"] == 1
    assert report["passed"] == 0
    assert report["failed"] == 0
    assert report["errors"] == []


def test_tester_runs_tests(tmp_path):
    report = _agent()._run(_project(tmp_path), dry_run=False)
    assert report["dry_run"] is False
    assert report["status"] == "ok"
    assert report["returncode"] == 0
    assert report["collected"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0
    assert report["errors"] == []


def test_tester_missing_target_returns_error(tmp_path):
    report = _agent()._run(tmp_path / "missing", dry_run=True)
    assert report["status"] == "error"
    assert report["returncode"] is None
    assert report["errors"]


def test_tester_execute_requires_target():
    """Without a target param or files, execute fails with a validation error."""
    agent = _agent()
    result = agent.execute(AgentTask(description="run"), context=None)
    assert result.success is False
    assert result.errors == ["target is required"]
    assert result.error.code == RUNTIME_ERROR


def test_tester_execute_resolves_target_from_files(tmp_path):
    """When target is absent but files is set, files[0] becomes the target."""
    agent = _agent()
    ok_report = {"target": str(tmp_path), "dry_run": True, "status": "ok"}
    with patch.object(TesterAgent, "_run", return_value=ok_report) as run:
        result = agent.execute(
            AgentTask(description="run", files=[str(tmp_path)]),
            context=None,
        )
    run.assert_called_once_with(str(tmp_path), dry_run=True)
    assert result.success is True


def test_tester_execute_failure_on_error_report(tmp_path):
    agent = _agent()
    error_report = TesterAgent._error_report(str(tmp_path), True, "boom")
    with patch.object(TesterAgent, "_run", return_value=error_report):
        result = agent.execute(
            AgentTask(description="run", params={"target": str(tmp_path)}),
            context=None,
        )
    assert result.success is False
    assert result.errors == ["boom"]
    assert result.error.code == RUNTIME_ERROR
    assert result.error.message == "boom"


def test_tester_execute_error_with_no_errors_uses_fallback(tmp_path):
    agent = _agent()
    with patch.object(TesterAgent, "_run", return_value={"status": "error", "errors": []}):
        result = agent.execute(
            AgentTask(description="run", params={"target": str(tmp_path)}),
            context=None,
        )
    assert result.success is False
    assert result.error.message == "Test run failed"


def test_tester_run_subprocess_failure_returns_error(tmp_path):
    agent = _agent()
    with (
        patch.object(TesterAgent, "_collect_count", return_value=0),
        patch("aios.agents.tester.subprocess.run", side_effect=OSError("pytest missing")),
    ):
        report = agent._run(tmp_path, dry_run=False)
    assert report["status"] == "error"
    assert report["errors"] == ["pytest missing"]


def test_tester_run_timeout_returns_error(tmp_path):
    agent = _agent()
    with (
        patch.object(TesterAgent, "_collect_count", return_value=0),
        patch(
            "aios.agents.tester.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pytest", 120),
        ),
    ):
        report = agent._run(tmp_path, dry_run=False)
    assert report["status"] == "error"
    assert report["errors"]


def test_tester_collect_count_returns_zero_on_subprocess_error(tmp_path):
    agent = _agent()
    with patch("aios.agents.tester.subprocess.run", side_effect=OSError("boom")):
        assert agent._collect_count(tmp_path) == 0
