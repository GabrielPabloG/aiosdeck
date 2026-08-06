"""Tests for ReviewerAgent — deterministic review() API and execute() delegation."""

import json
from pathlib import Path

from aios.agents.models import AgentResult
from aios.agents.reviewer import ReviewerAgent
from aios.core.task import Task

FIXTURE = Path(__file__).parent / "fixtures" / "simple_repo"


def _agent(level: str | None = None) -> ReviewerAgent:
    return ReviewerAgent(level=level)


def test_reviewer_capabilities():
    assert "ask_user" not in ReviewerAgent.required_capabilities
    assert "filesystem_write" not in ReviewerAgent.required_capabilities
    assert "shell" not in ReviewerAgent.required_capabilities
    assert "filesystem_read" in ReviewerAgent.required_capabilities


def test_review_returns_structured_dict():
    report = _agent().review(FIXTURE)
    assert set(report) == {"items", "stats", "summary"}
    assert isinstance(report["items"], list)
    assert set(report["stats"]) == {"errors", "warnings", "infos"}


def test_review_detects_todo_and_missing_docstring():
    report = _agent().review(FIXTURE)
    rules = {item["rule"] for item in report["items"]}
    assert "todo-detection" in rules
    assert "missing-module-docstring" in rules
    assert all(item["severity"] in ("error", "warning", "info") for item in report["items"])


def test_review_clean_file_has_no_findings():
    report = _agent().review(FIXTURE / "bar.py")
    assert report["items"] == []
    assert report["stats"] == {"errors": 0, "warnings": 0, "infos": 0}


def test_review_security_level_detects_secrets():
    report = _agent(level="security").review(FIXTURE)
    rules = {item["rule"] for item in report["items"]}
    assert "hardcoded-secret" in rules
    assert "unsafe-eval" in rules
    secrets = [item for item in report["items"] if item["rule"] == "hardcoded-secret"]
    assert all(item["severity"] == "error" for item in secrets)


def test_review_architecture_level_detects_missing_init():
    report = _agent(level="architecture").review(FIXTURE)
    rules = {item["rule"] for item in report["items"]}
    assert "missing-package-init" in rules


def test_review_missing_target_returns_error():
    report = _agent().review("/nonexistent/path/for/review")
    assert report["items"] == []
    assert "target not found" in report["summary"]


def test_review_item_fields():
    report = _agent().review(FIXTURE / "foo.py")
    item = report["items"][0]
    assert set(item) == {
        "id",
        "rule",
        "severity",
        "file",
        "line",
        "message",
        "suggestion",
    }
    assert item["file"] == "foo.py"
    assert item["line"] > 0


def test_review_does_not_write_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("# TODO: fix this\nvalue = 1\n", encoding="utf-8")
    before = {p.name: p.stat().st_mtime_ns for p in src.iterdir()}
    _agent().review(src)
    after = {p.name: p.stat().st_mtime_ns for p in src.iterdir()}
    assert before == after


def test_execute_delegates_to_review():
    result = _agent().execute(Task(description="review", task_type="conventions"), None)
    assert isinstance(result, AgentResult)
    assert result.success is True
    report = json.loads(result.output)
    assert "items" in report and "stats" in report and "summary" in report


def test_execute_with_files_target():
    result = _agent().execute(
        Task(description="review file", files=[str(FIXTURE / "bar.py")]),
        None,
    )
    report = json.loads(result.output)
    assert report["items"] == []
