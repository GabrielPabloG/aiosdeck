"""Tests for the security CLI — `aios policy show` and `aios security stats`.

The policy view is static and read-only: canonical capabilities per agent,
the safe default intents, and the additive expansion table. The stats view is
the queryable allow/deny audit trail persisted by the telemetry engine.
"""

import json
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

from aios.cli.commands import COMMANDS
from aios.core import Kernel
from aios.core.run_result import RunResult, StageSummary
from aios.security.actions import (
    DEFAULT_INTENTS,
    FILESYSTEM_READ_ACTION,
    SHELL_EXECUTE,
)
from aios.security.cli import (
    _parse_security_filters,
    _render_intent_summary,
    cmd_policy_show,
    cmd_security_stats,
)
from aios.telemetry.engine import TelemetryEngine


class TestCommandRegistration:
    def test_policy_command_registered(self):
        assert "policy" in COMMANDS
        assert "show" in COMMANDS["policy"].subcommands
        assert COMMANDS["policy"].subcommands["show"].execute is not None

    def test_security_command_registered(self):
        assert "security" in COMMANDS
        assert "stats" in COMMANDS["security"].subcommands
        assert COMMANDS["security"].subcommands["stats"].execute is not None


class TestPolicyShow:
    def test_policy_show_text(self, capsys):
        cmd_policy_show([], Path("/tmp"), lambda _: None)
        out = capsys.readouterr().out
        assert "Agent Capabilities" in out
        assert "developer" in out
        assert "Default Intents" in out
        assert "develop" in out
        assert "Capability Expansion" in out
        assert "filesystem.read" in out
        assert "release" in out  # the no-default note

    def test_policy_show_json(self, capsys):
        cmd_policy_show(["--json"], Path("/tmp"), lambda _: None)
        data = json.loads(capsys.readouterr().out)
        assert "capabilities" in data
        assert "intents" in data
        assert "expansion" in data
        assert "developer" in data["capabilities"]
        assert FILESYSTEM_READ_ACTION in data["expansion"]["filesystem_read"]
        assert "release" not in data["intents"]


def _telemetry(tmp_path):
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(tmp_path / "test.db"))
    engine.initialize()
    engine._store.insert_security_decision(
        {
            "decision": "security.check.denied",
            "agent": "git",
            "action": "review",
            "allowed": False,
            "reason": "no overlap",
            "violations": ["git.branch", "git.commit"],
            "intent_source": "default",
            "correlation_id": "run-1",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )
    engine._store.insert_security_decision(
        {
            "decision": "security.check.passed",
            "agent": "developer",
            "allowed": True,
            "intent_source": "default",
        }
    )
    return engine


class TestParseSecurityFilters:
    def test_no_args(self):
        assert _parse_security_filters([]) == {"limit": 100}

    def test_json_and_records(self):
        f = _parse_security_filters(["--json", "--records", "--decision", "security.check.denied"])
        assert f["json"] is True
        assert f["records"] is True
        assert f["decision"] == "security.check.denied"

    def test_unknown_option(self):
        with suppress(SystemExit):
            _parse_security_filters(["--nope"])


class TestSecurityStats:
    def test_stats_json(self, tmp_path, capsys):
        engine = _telemetry(tmp_path)
        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)
        with patch.object(kernel, "start", lambda: None):
            cmd_security_stats(["--json"], Path(tmp_path), lambda _: kernel)
        data = json.loads(capsys.readouterr().out)
        decisions = {row["decision"] for row in data}
        assert decisions == {"security.check.denied", "security.check.passed"}
        denied = next(r for r in data if r["decision"] == "security.check.denied")
        assert denied["denied"] == 1
        engine.shutdown()

    def test_records_json(self, tmp_path, capsys):
        engine = _telemetry(tmp_path)
        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(engine)
        with patch.object(kernel, "start", lambda: None):
            cmd_security_stats(["--records", "--json"], Path(tmp_path), lambda _: kernel)
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2
        denied = next(r for r in data if r["decision"] == "security.check.denied")
        assert denied["violations"] == ["git.branch", "git.commit"]
        engine.shutdown()

    def test_stats_unavailable_engine(self, tmp_path, capsys):
        kernel = Kernel(project_path=str(tmp_path))
        with patch.object(kernel, "start", lambda: None):
            cmd_security_stats([], Path(tmp_path), lambda _: kernel)
        assert "not available" in capsys.readouterr().out


class TestIntentSummary:
    def test_render_intent_summary(self, capsys):
        result = RunResult(
            success=True,
            stages=(
                StageSummary(
                    name="planner",
                    details={
                        "effective": ["ask_user", "filesystem.read"],
                        "intent": {"name": "develop", "source": "default"},
                    },
                ),
                StageSummary(
                    name="developer:1",
                    details={"effective": ["filesystem.read", "shell.execute"]},
                ),
            ),
        )
        _render_intent_summary(result)
        captured = capsys.readouterr()
        assert "intent: develop (source: default)" in captured.err
        assert "filesystem.read" in captured.err
        assert SHELL_EXECUTE in captured.err

    def test_render_intent_summary_empty(self, capsys):
        _render_intent_summary(RunResult(success=True, stages=()))
        captured = capsys.readouterr()
        assert captured.err == ""


class TestWorkflowStageEffective:
    def test_workflow_stages_carry_effective_and_intent(self, tmp_path):  # noqa: PLR0915 - fixture setup
        import subprocess
        from unittest.mock import MagicMock

        from aios.agents.developer import DeveloperAgent
        from aios.agents.documentation import DocumentationAgent
        from aios.agents.executor import AgentExecutor
        from aios.agents.git import GitAgent
        from aios.agents.planner import PlannerAgent
        from aios.agents.reviewer import ReviewerAgent
        from aios.agents.tester import TesterAgent
        from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
        from aios.core.task import Task
        from aios.scheduler import KanbanEngine
        from aios.workflow import WorkflowEngine

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        src = repo / "src"
        src.mkdir()
        (src / "base.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_app.py").write_text(
            "def test_main():\n    assert True\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
        scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
        scheduler.initialize()
        executor = AgentExecutor()
        workflow = WorkflowEngine(
            planner=PlannerAgent(MagicMock()),
            scheduler=scheduler,
            developer=DeveloperAgent(MagicMock()),
            reviewer=ReviewerAgent(),
            tester=TesterAgent(),
            documentation=DocumentationAgent(docs_dir=str(repo / "docs")),
            git=GitAgent(repository=repo),
            project_path=repo,
            executor=executor,
        )
        workflow._agents["git"].push = MagicMock()
        planner = workflow._agents["planner"]
        planner._runtime.execute.return_value = json.dumps(
            {
                "goal": "g",
                "subtasks": [
                    {"id": "1", "description": "task", "type": "code", "priority": "high"}
                ],
                "risks": [],
                "unknowns": [],
            }
        )
        dev = workflow._agents["developer"]._runtime

        def _dev_execute(*_args, **_kwargs):
            (repo / "src" / "health_endpoint.py").write_text(
                'def health():\n    return "ok"\n', encoding="utf-8"
            )
            return "Implementation complete."

        dev.execute.side_effect = _dev_execute
        ctx = ContextPacket()
        ctx.project = ProjectInfo(language="python", root=str(repo), name="test")
        ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
        ctx.git = GitInfo(branch="main", status="clean")
        try:
            result = workflow.execute(Task(description="g"), ctx)
            assert result.success is True
            dev_stage = next(s for s in result.stages if s.name.startswith("developer:"))
            assert "effective" in dev_stage.details
            assert FILESYSTEM_READ_ACTION in dev_stage.details["effective"]
            assert "intent" in dev_stage.details
            assert dev_stage.details["intent"]["name"] == "develop"
            assert dev_stage.details["intent"]["source"] == "default"
        finally:
            scheduler.shutdown()


def test_default_intents_never_grant_release():
    assert "release" not in DEFAULT_INTENTS
