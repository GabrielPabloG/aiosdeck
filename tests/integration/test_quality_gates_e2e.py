"""End-to-end quality gates in the workflow pipeline.

Mirrors the WorkflowEngine setup from test_workflow.py but injects a
QualityConfig and deterministic fake gates so the full gate chain
(block / advance / skip / override) can be exercised without network or LLM.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.executor import AgentExecutor
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.config.schema import QualityConfig
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.task import Task
from aios.quality.contracts import GateFinding, GateResult, GateStatus, Severity
from aios.scheduler import KanbanEngine
from aios.workflow import WorkflowEngine

VALID_PLAN = {
    "goal": "Add endpoint /health",
    "subtasks": [
        {"id": "1", "description": "Create /health route handler", "type": "code"},
        {"id": "2", "description": "Add tests for /health endpoint", "type": "test"},
    ],
    "risks": [],
    "unknowns": [],
}

GATE_ORDER = [
    "code_gate",
    "reviewer",
    "security_gate",
    "tester",
    "test_gate",
    "documentation",
    "documentation_gate",
]


class _FakeGate:
    def __init__(self, result):
        self.name = "fake_gate"
        self._result = result

    def is_applicable(self, gate_input):
        return True

    async def run(self, gate_input):
        return self._result


def _passed() -> GateResult:
    return GateResult(status=GateStatus.PASSED, reason="ok")


def _skipped() -> GateResult:
    return GateResult(status=GateStatus.SKIPPED, reason="not applicable")


def _failed(*severities: Severity) -> GateResult:
    findings = [
        GateFinding(id=f"F{index}", title="finding", severity=severity)
        for index, severity in enumerate(severities)
    ]
    return GateResult(status=GateStatus.FAILED, reason="findings", findings=findings)


def _context(root: str) -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root=root, name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    return ctx


def _setup_project(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "health.py").write_text('"""Health module."""\ndef health_check():\n    return 1\n')
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_health.py").write_text("def test_health_check():\n    assert True\n")
    return repo


_UNSET = object()


def _make_workflow(  # noqa: PLR0913 - test builder convenience
    tmp_path: Path,
    repo: Path,
    gates: dict,
    *,
    environment: str = "dev",
    overrides: list[dict] | None = None,
    quality_config: QualityConfig | None | object = _UNSET,
) -> tuple[WorkflowEngine, KanbanEngine]:
    scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()
    if quality_config is _UNSET:
        quality_config = QualityConfig(environment=environment)
        if overrides is not None:
            quality_config.overrides = overrides

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow = WorkflowEngine(
        planner=PlannerAgent(planner_runtime),
        scheduler=scheduler,
        developer=DeveloperAgent(dev_runtime),
        reviewer=ReviewerAgent(),
        tester=TesterAgent(),
        documentation=DocumentationAgent(docs_dir=str(repo / "docs")),
        git=GitAgent(repository=repo),
        project_path=repo,
        executor=AgentExecutor(),
        quality_config=quality_config,
        quality_gates=gates,
    )
    return workflow, scheduler


def _run(workflow, repo):
    return workflow.execute(Task(description="Add endpoint /health"), _context(str(repo)))


def _all_passing_gates() -> dict:
    return {name: _FakeGate(_passed()) for name in GATE_ORDER}


def _release_gates() -> dict:
    gates = _all_passing_gates()
    gates["release_gate"] = _FakeGate(_skipped())
    return gates


def test_all_gates_passing_succeeds(tmp_path):
    repo = _setup_project(tmp_path)
    workflow, scheduler = _make_workflow(tmp_path, repo, _all_passing_gates())
    try:
        result = _run(workflow, repo)
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
    repo = _setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = _FakeGate(_failed(Severity.HIGH))
    workflow, scheduler = _make_workflow(tmp_path, repo, gates)
    try:
        result = _run(workflow, repo)
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
    repo = _setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = _FakeGate(_failed(Severity.MEDIUM))
    workflow, scheduler = _make_workflow(tmp_path, repo, gates, environment="dev")
    try:
        result = _run(workflow, repo)
        assert result.success is True
        code_stage = next(s for s in result.stages if s.name == "code_gate")
        assert code_stage.success is True
        assert code_stage.details["policy"]["decision"] == "warn"
    finally:
        scheduler.shutdown()


def test_medium_in_release_blocks(tmp_path):
    repo = _setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = _FakeGate(_failed(Severity.MEDIUM))
    workflow, scheduler = _make_workflow(tmp_path, repo, gates, environment="release")
    try:
        result = _run(workflow, repo)
        assert result.success is False
        assert result.stages[-1].name == "code_gate"
        assert result.stages[-1].success is False
    finally:
        scheduler.shutdown()


def test_skipped_gate_advances_with_annotation(tmp_path):
    repo = _setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["security_gate"] = _FakeGate(_skipped())
    workflow, scheduler = _make_workflow(tmp_path, repo, gates)
    try:
        result = _run(workflow, repo)
        assert result.success is True
        security_stage = next(s for s in result.stages if s.name == "security_gate")
        assert security_stage.success is True
        assert security_stage.details["skipped"] is True
        assert security_stage.details["gate"]["status"] == "skipped"
    finally:
        scheduler.shutdown()


def test_override_lifts_block_in_dev(tmp_path):
    repo = _setup_project(tmp_path)
    gates = _all_passing_gates()
    gates["code_gate"] = _FakeGate(_failed(Severity.HIGH))
    overrides = [{"gate": "code_gate", "environment": "dev", "reason": "manual review ok"}]
    workflow, scheduler = _make_workflow(tmp_path, repo, gates, overrides=overrides)
    try:
        result = _run(workflow, repo)
        assert result.success is True
        code_stage = next(s for s in result.stages if s.name == "code_gate")
        assert code_stage.success is True
        assert code_stage.details["policy"]["overridden"] is True
        assert code_stage.details["policy"]["override_reason"] == "manual review ok"
    finally:
        scheduler.shutdown()


def test_release_gate_runs_skipped_in_release_env(tmp_path):
    repo = _setup_project(tmp_path)
    workflow, scheduler = _make_workflow(tmp_path, repo, _release_gates(), environment="release")
    try:
        result = _run(workflow, repo)
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
    repo = _setup_project(tmp_path)
    workflow, scheduler = _make_workflow(tmp_path, repo, _release_gates(), environment="dev")
    try:
        result = _run(workflow, repo)
        assert result.success is True
        assert all(s.name != "release_gate" for s in result.stages)
    finally:
        scheduler.shutdown()


def test_without_quality_config_no_gate_stages(tmp_path):
    repo = _setup_project(tmp_path)
    workflow, scheduler = _make_workflow(tmp_path, repo, _all_passing_gates(), quality_config=None)
    try:
        result = _run(workflow, repo)
        assert result.success is True
        names = [s.name for s in result.stages]
        assert "code_gate" not in names
        assert "security_gate" not in names
        assert "test_gate" not in names
        assert "documentation_gate" not in names
    finally:
        scheduler.shutdown()
