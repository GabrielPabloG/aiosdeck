"""Tests for TesterAgent — dry-run collection and structured report."""

import shutil
from pathlib import Path

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
