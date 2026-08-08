"""Behaviour tests for the concrete quality gates.

Every gate is exercised with passed / failed / skipped / error cases.
All tests are 100% local: temp projects on disk, no network, no LLM.
"""

import asyncio
from pathlib import Path

import pytest

from aios.quality import (
    CodeGate,
    DocumentationGate,
    GateInput,
    GateStatus,
    ReleaseGate,
    SecurityGate,
    Severity,
    TestGate,
)

PYTHON = None


def _await(coro):
    return asyncio.run(coro)


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


class TestCodeGate:
    def test_passed_on_clean_project(self, tmp_path):
        _write(tmp_path / "app.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
        gate = CodeGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.PASSED
        assert result.findings == []

    def test_failed_on_lint_errors(self, tmp_path):
        _write(tmp_path / "app.py", "import os\n")
        gate = CodeGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.FAILED
        assert result.findings
        assert all(f.severity is Severity.HIGH for f in result.findings)

    def test_skipped_when_no_python_files(self, tmp_path):
        gate = CodeGate()
        gate_input = GateInput(project_path=tmp_path)
        assert gate.is_applicable(gate_input) is False
        result = _await(gate.run(gate_input))
        assert result.status is GateStatus.SKIPPED

    def test_error_when_runtime_missing(self, tmp_path):
        _write(tmp_path / "app.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
        gate = CodeGate(python="/nonexistent/bin/python")
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.ERROR
        assert "ruff" in result.reason or "python" in result.reason.lower()


class TestTestGate:
    def test_passed_when_no_failures(self):
        gate = TestGate()
        gate_input = GateInput(
            test_report={"status": "ok", "collected": 4, "passed": 4, "failed": 0}
        )
        result = _await(gate.run(gate_input))
        assert result.status is GateStatus.PASSED
        assert result.metadata["passed"] == 4

    def test_failed_when_failures(self):
        gate = TestGate()
        result = _await(gate.run(GateInput(test_report={"failed": 2, "passed": 1})))
        assert result.status is GateStatus.FAILED
        assert result.findings
        assert result.findings[0].id == "test-failures"

    def test_skipped_without_report(self):
        gate = TestGate()
        gate_input = GateInput()
        assert gate.is_applicable(gate_input) is False
        result = _await(gate.run(gate_input))
        assert result.status is GateStatus.SKIPPED

    def test_error_on_runner_error(self):
        gate = TestGate()
        result = _await(
            gate.run(GateInput(test_report={"status": "error", "errors": ["target not found"]}))
        )
        assert result.status is GateStatus.ERROR
        assert result.findings
        assert result.findings[0].severity is Severity.HIGH


class TestSecurityGate:
    def test_passed_on_clean_file(self, tmp_path):
        _write(tmp_path / "app.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
        gate = SecurityGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.PASSED

    def test_failed_on_hardcoded_secret(self, tmp_path):
        _write(tmp_path / "app.py", 'password = "hunter2"\n')
        gate = SecurityGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.FAILED
        assert result.findings
        assert result.findings[0].severity is Severity.HIGH

    def test_failed_on_unsafe_eval(self, tmp_path):
        _write(tmp_path / "app.py", "code = eval(user_input)\n")
        gate = SecurityGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.FAILED
        assert any(f.id == "unsafe-eval" for f in result.findings)

    def test_skipped_without_files(self, tmp_path):
        gate = SecurityGate()
        gate_input = GateInput(project_path=tmp_path)
        assert gate.is_applicable(gate_input) is False
        result = _await(gate.run(gate_input))
        assert result.status is GateStatus.SKIPPED


class TestDocumentationGate:
    def test_passed_when_changelog_has_unreleased(self, tmp_path):
        _write(tmp_path / "CHANGELOG.md", "# Changelog\n\n## Unreleased\n\n- change\n")
        gate = DocumentationGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.PASSED

    def test_failed_when_changelog_missing_entry(self, tmp_path):
        _write(tmp_path / "CHANGELOG.md", "# Changelog\n\n## 1.0.0 - 2020-01-01\n\n- old\n")
        gate = DocumentationGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.FAILED
        assert result.findings[0].id == "changelog-missing-entry"

    def test_failed_when_todo_has_blockers(self, tmp_path):
        _write(tmp_path / "TODO.md", "- [ ] ship it\n- [ ] BLOCKED on review\n")
        gate = DocumentationGate()
        result = _await(gate.run(GateInput(project_path=tmp_path)))
        assert result.status is GateStatus.FAILED
        assert any(f.id == "todo-blockers" for f in result.findings)

    def test_skipped_without_docs(self, tmp_path):
        gate = DocumentationGate()
        gate_input = GateInput(project_path=tmp_path)
        assert gate.is_applicable(gate_input) is False
        result = _await(gate.run(gate_input))
        assert result.status is GateStatus.SKIPPED


class TestReleaseGate:
    def test_skipped_by_default(self):
        gate = ReleaseGate()
        assert gate.name == "release_gate"
        assert gate.is_applicable(GateInput()) is False
        result = _await(gate.run(GateInput()))
        assert result.status is GateStatus.SKIPPED


@pytest.mark.parametrize(
    "gate",
    [
        CodeGate(),
        TestGate(),
        SecurityGate(),
        DocumentationGate(),
        ReleaseGate(),
    ],
)
def test_all_gates_expose_name(gate):
    assert gate.name
    assert gate.name.endswith("_gate")
