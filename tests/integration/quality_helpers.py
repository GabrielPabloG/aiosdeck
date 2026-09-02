"""Shared fixtures for quality-gate workflow e2e tests.

WorkflowEngine needs a real project on disk (git repo, tests) and mock
runtimes for planner/developer. These helpers keep the quality e2e tests
deterministic: injected fake gates control every outcome.
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

_UNSET = object()


class FakeGate:
    def __init__(self, result):
        self.name = "fake_gate"
        self._result = result

    def is_applicable(self, gate_input):
        return True

    async def run(self, gate_input):
        return self._result


def passed() -> GateResult:
    return GateResult(status=GateStatus.PASSED, reason="ok")


def skipped() -> GateResult:
    return GateResult(status=GateStatus.SKIPPED, reason="not applicable")


def failed(*severities: Severity) -> GateResult:
    findings = [
        GateFinding(id=f"F{index}", title="finding", severity=severity)
        for index, severity in enumerate(severities)
    ]
    return GateResult(status=GateStatus.FAILED, reason="findings", findings=findings)


def context(root: str) -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root=root, name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    return ctx


def setup_project(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    src = repo / "src"
    src.mkdir()
    (src / "base.py").write_text("x = 1\n")
    (repo / "health.py").write_text('"""Health module."""\ndef health_check():\n    return 1\n')
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_health.py").write_text("def test_health_check():\n    assert True\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
    return repo


def make_workflow(  # noqa: PLR0913 - test builder convenience
    tmp_path: Path,
    repo: Path,
    gates: dict,
    *,
    environment: str = "dev",
    overrides: list[dict] | None = None,
    quality_config: QualityConfig | None | object = _UNSET,
    bus=None,
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

    def _dev_execute(*_args, **_kwargs):
        (repo / "src" / "health_endpoint.py").write_text(
            'def health():\n    return "ok"\n', encoding="utf-8"
        )
        return "Implementation complete."

    dev_runtime.execute.side_effect = _dev_execute

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
    if bus is not None:
        workflow.set_event_bus(bus)
    return workflow, scheduler


def run_workflow(workflow: WorkflowEngine, repo: Path):
    return workflow.execute(Task(description="Add endpoint /health"), context(str(repo)))
