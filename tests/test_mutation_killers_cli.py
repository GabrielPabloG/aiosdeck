"""Mutation-killing tests for CLI commands — doctor, route_stats, skills, plan.

Targets STRING_MUTATION (assert exact output strings), ARG_REMOVAL (verify
each argument affects output), and CONSTANT_REPLACEMENT (assert specific
numbers) survivors.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aios.cli.commands.core import cmd_doctor, cmd_init
from aios.cli.commands.exec_cmds import (
    _gate_label,
    _gates_json,
    _render_gate_trail,
    _render_plan_list,
    _render_run_result,
    _render_stage,
    _run_result_to_json,
    cmd_plan,
)
from aios.core.run_result import RunResult, StageSummary
from aios.routing.cli import (
    cmd_route,
    cmd_route_explain,
    cmd_route_stats,
    _parse_explain_args,
    _parse_stats_args,
)
from aios.skills.cli import cmd_skills_discover, cmd_skills_inspect, cmd_skills_stats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_kernel(
    *,
    status_fn=None,
    context=None,
    telemetry=None,
    knowledge=None,
    config=None,
    start_raises=None,
):
    kernel = MagicMock()
    if start_raises:
        kernel.start.side_effect = start_raises
    kernel.status.return_value = status_fn() if status_fn else {
        "version": "1.0.0",
        "engines": {"telemetry": "ready"},
        "errors": [],
    }
    kernel.get_context.return_value = context
    kernel.get_engine.side_effect = lambda name: {
        "telemetry": telemetry,
        "knowledge": knowledge,
        "config": config,
    }.get(name)
    return kernel


def _factory(kernel):
    def _build(project_path):
        return kernel
    return _build


# ===========================================================================
# cmd_doctor
# ===========================================================================


class TestCmdDoctor:
    def test_json_mode_outputs_json(self, tmp_path, capsys):
        ctx = MagicMock()
        ctx.project.language = "python"
        ctx.tools.linter = "ruff"
        ctx.tools.formatter = "black"
        ctx.tools.test_runner = "pytest"
        ctx.git.branch = "main"
        ctx.git.status = "clean"
        ctx.runtime.opencode = True
        ctx.runtime.ai_jail = False
        kernel = _make_kernel(context=ctx)
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert "version" in out
        assert "context" in out
        assert out["context"]["language"] == "python"
        assert out["context"]["linter"] == "ruff"
        assert out["context"]["formatter"] == "black"
        assert out["context"]["test_runner"] == "pytest"
        assert out["context"]["git_branch"] == "main"
        assert out["context"]["git_status"] == "clean"
        assert out["context"]["opencode"] is True
        assert out["context"]["ai_jail"] is False

    def test_json_mode_without_context(self, tmp_path, capsys):
        kernel = _make_kernel(context=None)
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert "version" in out
        assert "context" not in out

    def test_json_mode_with_diagnostics(self, tmp_path, capsys):
        kernel = _make_kernel(context=None)
        kernel.status.return_value = {
            "version": "1.0.0",
            "engines": {},
            "errors": [],
            "runtime_diagnostics": {
                "status": "ok",
                "code": 0,
                "provider": "ollama",
                "model": "llama3",
                "source": "env",
                "suggestions": ["install ollama"],
            },
        }
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert "runtime_diagnostics" in out
        assert out["runtime_diagnostics"]["status"] == "ok"
        assert out["runtime_diagnostics"]["provider"] == "ollama"

    def test_json_mode_with_errors(self, tmp_path, capsys):
        kernel = _make_kernel(context=None)
        kernel.status.return_value = {
            "version": "1.0.0",
            "engines": {},
            "errors": ["something broke"],
        }
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["errors"] == ["something broke"]

    def test_logger_mode_with_context(self, tmp_path, capsys):
        ctx = MagicMock()
        ctx.project.language = "python"
        ctx.tools.linter = "ruff"
        ctx.tools.formatter = ""
        ctx.tools.test_runner = "pytest"
        ctx.git.branch = "main"
        ctx.git.status = "dirty"
        ctx.runtime.opencode = False
        ctx.runtime.ai_jail = True
        kernel = _make_kernel(context=ctx)
        cmd_doctor([], tmp_path, _factory(kernel))
        # Logger mode writes to logging, not stdout/stderr directly
        # Just verify no exception

    def test_logger_mode_without_context(self, tmp_path):
        kernel = _make_kernel(context=None)
        cmd_doctor([], tmp_path, _factory(kernel))

    def test_logger_mode_with_diagnostics(self, tmp_path):
        ctx = MagicMock()
        ctx.project.language = "python"
        ctx.tools.linter = "ruff"
        ctx.tools.formatter = ""
        ctx.tools.test_runner = "pytest"
        ctx.git.branch = "main"
        ctx.git.status = "clean"
        ctx.runtime.opencode = False
        ctx.runtime.ai_jail = False
        kernel = _make_kernel(context=ctx)
        kernel.status.return_value = {
            "version": "1.0.0",
            "engines": {},
            "errors": [],
            "runtime_diagnostics": {
                "status": "ok",
                "code": 0,
                "provider": "ollama",
                "model": "llama3",
                "source": "env",
                "suggestions": [],
            },
        }
        cmd_doctor([], tmp_path, _factory(kernel))

    def test_logger_mode_with_errors(self, tmp_path):
        ctx = MagicMock()
        ctx.project.language = "python"
        ctx.tools.linter = "ruff"
        ctx.tools.formatter = ""
        ctx.tools.test_runner = "pytest"
        ctx.git.branch = "main"
        ctx.git.status = "clean"
        ctx.runtime.opencode = False
        ctx.runtime.ai_jail = False
        kernel = _make_kernel(context=ctx)
        kernel.status.return_value = {
            "version": "1.0.0",
            "engines": {},
            "errors": ["warning 1", "warning 2"],
        }
        cmd_doctor([], tmp_path, _factory(kernel))

    def test_json_mode_diagnose_runtime_called(self, tmp_path, capsys):
        kernel = _make_kernel(context=None)
        kernel.diagnose_runtime = MagicMock()
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        kernel.diagnose_runtime.assert_called_once()

    def test_json_mode_status_fields(self, tmp_path, capsys):
        kernel = _make_kernel(context=None)
        kernel.status.return_value = {
            "version": "2.0.0",
            "engines": {"telemetry": "ready", "knowledge": "ready"},
            "errors": [],
        }
        cmd_doctor(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["version"] == "2.0.0"
        assert out["engines"]["telemetry"] == "ready"
        assert out["engines"]["knowledge"] == "ready"


# ===========================================================================
# cmd_init
# ===========================================================================


class TestCmdInit:
    def test_creates_aios_dir(self, tmp_path):
        cmd_init([], tmp_path, _factory(MagicMock()))
        assert (tmp_path / ".aios").is_dir()
        assert (tmp_path / ".aios" / "project.yaml").exists()

    def test_creates_gitignore_rule(self, tmp_path):
        cmd_init([], tmp_path, _factory(MagicMock()))
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        assert ".aios/memory.db" in gi.read_text()

    def test_idempotent(self, tmp_path):
        cmd_init([], tmp_path, _factory(MagicMock()))
        cmd_init([], tmp_path, _factory(MagicMock()))
        gi = tmp_path / ".gitignore"
        assert gi.read_text().count(".aios/memory.db") == 1

    def test_preserves_existing_gitignore(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        cmd_init([], tmp_path, _factory(MagicMock()))
        text = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in text
        assert ".aios/memory.db" in text

    def test_project_name_in_yaml(self, tmp_path):
        cmd_init([], tmp_path, _factory(MagicMock()))
        yaml_text = (tmp_path / ".aios" / "project.yaml").read_text()
        assert tmp_path.name in yaml_text
        assert "runtime: opencode" in yaml_text
        assert "sandbox: ai-jail" in yaml_text
        assert "skills:" in yaml_text


# ===========================================================================
# cmd_route_stats
# ===========================================================================


class TestCmdRouteStats:
    def _make_telemetry(self, *, stats=None, records=None, accuracy=None):
        telemetry = MagicMock()
        telemetry.query_routing_stats.return_value = stats or []
        telemetry.query_routing_records.return_value = records or []
        telemetry.query_route_accuracy.return_value = accuracy or []
        return telemetry

    def test_stats_empty(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "No routing stats found." in out

    def test_stats_with_data(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[
            {"agent": "planner", "model": "gpt-4o", "routes": 10, "fallbacks": 2,
             "avg_estimated_cost": 0.001234, "avg_context_size": 500.0},
        ])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Routing stats" in out
        assert "planner" in out
        assert "gpt-4o" in out
        assert "routes=10" in out
        assert "fallbacks=2" in out

    def test_stats_json_mode(self, tmp_path, capsys):
        stats = [{"agent": "planner", "model": "gpt-4o", "routes": 5}]
        telemetry = self._make_telemetry(stats=stats)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out == stats

    def test_records_empty(self, tmp_path, capsys):
        telemetry = self._make_telemetry(records=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--records"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "No routing records found." in out

    def test_records_with_data(self, tmp_path, capsys):
        records = [
            {"timestamp": "2024-01-10T12:00:00Z", "agent": "planner",
             "model": "gpt-4o", "estimated_cost": 0.001,
             "reason": "default", "fallback_used": False},
        ]
        telemetry = self._make_telemetry(records=records)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--records"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Routing records (1)" in out
        assert "planner" in out
        assert "gpt-4o" in out

    def test_records_with_fallback(self, tmp_path, capsys):
        records = [
            {"timestamp": "2024-01-10T12:00:00Z", "agent": "planner",
             "model": "gpt-4o", "estimated_cost": 0.001,
             "reason": "fallback", "fallback_used": True},
        ]
        telemetry = self._make_telemetry(records=records)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--records"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "FALLBACK" in out

    def test_records_json_mode(self, tmp_path, capsys):
        records = [{"timestamp": "2024-01-10T12:00:00Z", "agent": "planner"}]
        telemetry = self._make_telemetry(records=records)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--records", "--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out == records

    def test_accuracy_empty(self, tmp_path, capsys):
        telemetry = self._make_telemetry(accuracy=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--accuracy"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "No route accuracy data available." in out

    def test_accuracy_with_data(self, tmp_path, capsys):
        accuracy = [
            {"agent": "planner", "model": "gpt-4o",
             "estimated_cost": 0.001, "actual_cost": 0.0012, "delta": 0.0002},
        ]
        telemetry = self._make_telemetry(accuracy=accuracy)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--accuracy"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Route accuracy (1 records)" in out
        assert "planner" in out
        assert "gpt-4o" in out

    def test_accuracy_negative_delta(self, tmp_path, capsys):
        accuracy = [
            {"agent": "planner", "model": "gpt-4o",
             "estimated_cost": 0.002, "actual_cost": 0.001, "delta": -0.001},
        ]
        telemetry = self._make_telemetry(accuracy=accuracy)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--accuracy"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "-$" in out

    def test_accuracy_json_mode(self, tmp_path, capsys):
        accuracy = [{"agent": "planner", "model": "gpt-4o", "delta": 0.001}]
        telemetry = self._make_telemetry(accuracy=accuracy)
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--accuracy", "--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out == accuracy

    def test_telemetry_none_exits(self, tmp_path):
        kernel = _make_kernel(telemetry=None)
        with pytest.raises(SystemExit) as exc_info:
            cmd_route_stats([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_agent_filter_passed(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[
            {"agent": "planner", "model": "gpt-4o", "routes": 5,
             "fallbacks": 0, "avg_estimated_cost": 0.001, "avg_context_size": 100.0},
        ])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--agent", "planner"], tmp_path, _factory(kernel))
        telemetry.query_routing_stats.assert_called_once()
        call_kwargs = telemetry.query_routing_stats.call_args
        assert call_kwargs.kwargs.get("agent") == "planner" or call_kwargs[1].get("agent") == "planner"

    def test_model_filter_passed(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[
            {"agent": "planner", "model": "gpt-4o", "routes": 5,
             "fallbacks": 0, "avg_estimated_cost": 0.001, "avg_context_size": 100.0},
        ])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--model", "gpt-4o"], tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_routing_stats.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-4o" or call_kwargs[1].get("model") == "gpt-4o"

    def test_limit_passed(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--limit", "5"], tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_routing_stats.call_args
        assert call_kwargs.kwargs.get("limit") == 5 or call_kwargs[1].get("limit") == 5

    def test_records_limit_passed(self, tmp_path, capsys):
        telemetry = self._make_telemetry(records=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--records", "--limit", "3"], tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_routing_records.call_args
        assert call_kwargs.kwargs.get("limit") == 3 or call_kwargs[1].get("limit") == 3

    def test_date_filters_passed(self, tmp_path, capsys):
        telemetry = self._make_telemetry(stats=[])
        kernel = _make_kernel(telemetry=telemetry)
        cmd_route_stats(["--date-from", "2024-01-01", "--date-to", "2024-01-31"],
                        tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_routing_stats.call_args
        assert call_kwargs.kwargs.get("date_from") == "2024-01-01" or call_kwargs[1].get("date_from") == "2024-01-01"
        assert call_kwargs.kwargs.get("date_to") == "2024-01-31" or call_kwargs[1].get("date_to") == "2024-01-31"


# ===========================================================================
# cmd_route_explain
# ===========================================================================


class TestCmdRouteExplain:
    def test_explain_json(self, tmp_path, capsys):
        config = MagicMock()
        config.routing = MagicMock()
        kernel = _make_kernel(config=config)
        kernel.get_engine.return_value = config
        with patch("aios.routing.cli.RuleBasedRouter") as MockRouter:
            mock_decision = MagicMock()
            mock_decision.provider = "ollama"
            mock_decision.model = "llama3"
            mock_decision.variant = None
            mock_decision.reason = "default"
            mock_decision.estimated_cost = 0.0
            mock_decision.source = "default"
            mock_decision.fallback_chain = []
            MockRouter.return_value.route.return_value = mock_decision
            cmd_route_explain(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["provider"] == "ollama"
        assert out["model"] == "llama3"
        assert out["reason"] == "default"

    def test_explain_text(self, tmp_path, capsys):
        config = MagicMock()
        config.routing = MagicMock()
        kernel = _make_kernel(config=config)
        kernel.get_engine.return_value = config
        with patch("aios.routing.cli.RuleBasedRouter") as MockRouter:
            mock_decision = MagicMock()
            mock_decision.provider = "ollama"
            mock_decision.model = "llama3"
            mock_decision.variant = "fast"
            mock_decision.reason = "agent=planner"
            mock_decision.estimated_cost = 0.001234
            mock_decision.source = "default"
            mock_decision.fallback_chain = []
            MockRouter.return_value.route.return_value = mock_decision
            cmd_route_explain(["--agent", "planner"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Provider:" in out
        assert "ollama" in out
        assert "Model:" in out
        assert "llama3" in out
        assert "Variant:" in out
        assert "fast" in out
        assert "Reason:" in out
        assert "agent=planner" in out
        assert "Estimated cost:" in out
        assert "Source:" in out

    def test_explain_with_fallback_chain(self, tmp_path, capsys):
        config = MagicMock()
        config.routing = MagicMock()
        kernel = _make_kernel(config=config)
        kernel.get_engine.return_value = config
        with patch("aios.routing.cli.RuleBasedRouter") as MockRouter:
            mock_decision = MagicMock()
            mock_decision.provider = "openai"
            mock_decision.model = "gpt-4o"
            mock_decision.variant = None
            mock_decision.reason = "agent=developer"
            mock_decision.estimated_cost = 0.01
            mock_decision.source = "routing"
            mock_decision.fallback_chain = [
                {"provider": "ollama", "model": "llama3", "variant": None},
                {"provider": "openai", "model": "gpt-4o-mini", "variant": "fast"},
            ]
            MockRouter.return_value.route.return_value = mock_decision
            cmd_route_explain([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Fallback chain:" in out
        assert "ollama/llama3" in out
        assert "openai/gpt-4o-mini" in out
        assert "variant=fast" in out

    def test_no_routing_config_exits(self, tmp_path):
        kernel = _make_kernel(config=None)
        kernel.get_engine.return_value = None
        with pytest.raises(SystemExit) as exc_info:
            cmd_route_explain([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_parse_explain_args_defaults(self):
        opts = _parse_explain_args([])
        assert opts["agent"] == "planner"
        assert "json" not in opts

    def test_parse_explain_args_json(self):
        opts = _parse_explain_args(["--json"])
        assert opts["json"] is True

    def test_parse_explain_args_context_size(self):
        opts = _parse_explain_args(["--context-size", "1024"])
        assert opts["context_size"] == 1024

    def test_parse_stats_args_defaults(self):
        opts = _parse_stats_args([])
        assert opts["limit"] == 100

    def test_parse_stats_args_records(self):
        opts = _parse_stats_args(["--records"])
        assert opts["records"] is True

    def test_parse_stats_args_accuracy(self):
        opts = _parse_stats_args(["--accuracy"])
        assert opts["accuracy"] is True

    def test_parse_stats_args_limit(self):
        opts = _parse_stats_args(["--limit", "50"])
        assert opts["limit"] == 50

    def test_parse_stats_args_filters(self):
        opts = _parse_stats_args(["--agent", "planner", "--model", "gpt-4o"])
        assert opts["agent"] == "planner"
        assert opts["model"] == "gpt-4o"


# ===========================================================================
# cmd_route (dispatch)
# ===========================================================================


class TestCmdRoute:
    def test_no_args_exits(self, tmp_path):
        kernel = _make_kernel()
        with pytest.raises(SystemExit) as exc_info:
            cmd_route([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_unknown_subcommand_exits(self, tmp_path):
        kernel = _make_kernel()
        with pytest.raises(SystemExit) as exc_info:
            cmd_route(["unknown"], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1


# ===========================================================================
# cmd_skills_inspect
# ===========================================================================


class TestCmdSkillsInspect:
    def _make_registry(self, *, skill=None):
        registry = MagicMock()
        registry.get.return_value = skill
        return registry

    def test_no_args_exits(self, tmp_path):
        kernel = _make_kernel()
        with pytest.raises(SystemExit) as exc_info:
            cmd_skills_inspect([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_skill_not_found(self, tmp_path, capsys):
        registry = self._make_registry(skill=None)
        kernel = _make_kernel()
        with patch("aios.skills.cli.SkillRegistry", return_value=registry):
            with pytest.raises(SystemExit) as exc_info:
                cmd_skills_inspect(["nonexistent"], tmp_path, _factory(kernel))
            assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Skill not found: nonexistent" in out

    def test_skill_json_mode(self, tmp_path, capsys):
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "A test skill"
        skill.triggers = ["trigger1"]
        skill.scope = ["global"]
        skill.dependencies = []
        skill.priority = 5
        skill.version = "1.0"
        skill.owner = "test"
        skill.updated_at = "2024-01-01"
        skill.status = "active"
        skill.schema_version = 1
        registry = self._make_registry(skill=skill)
        knowledge = MagicMock()
        knowledge.list_sources.return_value = []
        kernel = _make_kernel(knowledge=knowledge)
        with patch("aios.skills.cli.SkillRegistry", return_value=registry):
            cmd_skills_inspect(["test-skill", "--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["name"] == "test-skill"
        assert out["description"] == "A test skill"
        assert out["triggers"] == ["trigger1"]
        assert out["scope"] == ["global"]
        assert out["priority"] == 5
        assert out["version"] == "1.0"
        assert out["owner"] == "test"
        assert out["status"] == "active"
        assert out["indexed"] is False
        assert out["chunks_count"] == 0

    def test_skill_text_mode(self, tmp_path, capsys):
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "A test skill"
        skill.triggers = ["trigger1"]
        skill.scope = ["global"]
        skill.dependencies = ["dep1"]
        skill.priority = 5
        skill.version = "1.0"
        skill.owner = "alice"
        skill.updated_at = "2024-01-01"
        skill.status = "active"
        skill.schema_version = 1
        registry = self._make_registry(skill=skill)
        knowledge = MagicMock()
        knowledge.list_sources.return_value = []
        kernel = _make_kernel(knowledge=knowledge)
        with patch("aios.skills.cli.SkillRegistry", return_value=registry):
            cmd_skills_inspect(["test-skill"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "test-skill" in out
        assert "A test skill" in out
        assert "active" in out
        assert "1.0" in out
        assert "alice" in out
        assert "trigger1" in out
        assert "global" in out
        assert "dep1" in out
        assert "no" in out  # indexed=no

    def test_skill_with_knowledge_indexed(self, tmp_path, capsys):
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "A test skill"
        skill.triggers = []
        skill.scope = []
        skill.dependencies = []
        skill.priority = 1
        skill.version = "1.0"
        skill.owner = ""
        skill.updated_at = ""
        skill.status = "active"
        skill.schema_version = 1
        registry = self._make_registry(skill=skill)
        source = MagicMock()
        source.path = "/skills/test-skill/skill.md"
        source.source_id = "src1"
        knowledge = MagicMock()
        knowledge.list_sources.return_value = [source]
        store = MagicMock()
        store.get_source_chunks.return_value = [1, 2, 3]
        knowledge._store = store
        kernel = _make_kernel(knowledge=knowledge)
        with patch("aios.skills.cli.SkillRegistry", return_value=registry):
            cmd_skills_inspect(["test-skill"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "yes" in out  # indexed=yes
        assert "3" in out  # chunks


# ===========================================================================
# cmd_skills_discover
# ===========================================================================


class TestCmdSkillsDiscover:
    def test_no_args_exits(self, tmp_path):
        kernel = _make_kernel()
        with pytest.raises(SystemExit) as exc_info:
            cmd_skills_discover([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_empty_results(self, tmp_path, capsys):
        kernel = _make_kernel()
        with patch("aios.skills.cli.SkillRegistry") as MockReg:
            with patch("aios.skills.cli.SkillDiscoveryService") as MockDisc:
                MockDisc.return_value.discover.return_value = []
                cmd_skills_discover(["test intent"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "No skills matched intent: test intent" in out

    def test_with_results_text(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = MagicMock()
        result.skill.name = "test-skill"
        result.skill.priority = 5
        result.skill.description = "A test skill"
        result.score = 0.95
        result.trigger_matches = ["trigger1"]
        result.scope_matches = ["global"]
        result.priority_score = 0.8
        with patch("aios.skills.cli.SkillRegistry") as MockReg:
            with patch("aios.skills.cli.SkillDiscoveryService") as MockDisc:
                MockDisc.return_value.discover.return_value = [result]
                cmd_skills_discover(["test intent"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Skill Discovery" in out
        assert "test intent" in out
        assert "test-skill" in out
        assert "0.95" in out
        assert "trigger1" in out
        assert "global" in out
        assert "Candidates: 1" in out

    def test_json_mode(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = MagicMock()
        result.skill.name = "test-skill"
        result.skill.priority = 5
        result.skill.description = "A test skill"
        result.score = 0.95
        result.trigger_matches = ["trigger1"]
        result.scope_matches = ["global"]
        result.priority_score = 0.8
        with patch("aios.skills.cli.SkillRegistry") as MockReg:
            with patch("aios.skills.cli.SkillDiscoveryService") as MockDisc:
                MockDisc.return_value.discover.return_value = [result]
                cmd_skills_discover(["test intent", "--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["intent"] == "test intent"
        assert out["candidates"] == 1
        assert out["skills"][0]["name"] == "test-skill"

    def test_agent_arg_passed(self, tmp_path, capsys):
        kernel = _make_kernel()
        with patch("aios.skills.cli.SkillRegistry") as MockReg:
            with patch("aios.skills.cli.SkillDiscoveryService") as MockDisc:
                MockDisc.return_value.discover.return_value = []
                cmd_skills_discover(["intent", "--agent", "developer"],
                                   tmp_path, _factory(kernel))
        MockDisc.assert_called_once()
        call_kwargs = MockDisc.call_args
        assert call_kwargs.kwargs.get("top_k") == 5 or call_kwargs[1].get("top_k") == 5


# ===========================================================================
# cmd_skills_stats
# ===========================================================================


class TestCmdSkillsStats:
    def test_no_telemetry(self, tmp_path, capsys):
        kernel = _make_kernel(telemetry=None)
        cmd_skills_stats([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Telemetry engine not available." in out

    def test_empty_stats(self, tmp_path, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = []
        kernel = _make_kernel(telemetry=telemetry)
        cmd_skills_stats([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "No skill usage records found." in out

    def test_stats_with_data(self, tmp_path, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = [
            {"skill_name": "test-skill", "total_used": 10,
             "total_selected": 5, "total_considered": 20,
             "avg_relevance": 0.75, "total_tokens": 1000},
        ]
        kernel = _make_kernel(telemetry=telemetry)
        cmd_skills_stats([], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "Skill Stats" in out
        assert "test-skill" in out
        assert "10" in out  # total_used
        assert "0.75" in out  # avg_relevance
        assert "1 skill(s)" in out

    def test_json_mode(self, tmp_path, capsys):
        telemetry = MagicMock()
        stats = [{"skill_name": "test-skill", "total_used": 10}]
        telemetry.query_skill_stats.return_value = stats
        kernel = _make_kernel(telemetry=telemetry)
        cmd_skills_stats(["--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out == stats

    def test_skill_filter_passed(self, tmp_path, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = []
        kernel = _make_kernel(telemetry=telemetry)
        cmd_skills_stats(["--skill", "test-skill"], tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_skill_stats.call_args
        assert call_kwargs.kwargs.get("skill") == "test-skill" or call_kwargs[1].get("skill") == "test-skill"

    def test_today_flag(self, tmp_path, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = []
        kernel = _make_kernel(telemetry=telemetry)
        cmd_skills_stats(["--today"], tmp_path, _factory(kernel))
        call_kwargs = telemetry.query_skill_stats.call_args
        assert call_kwargs.kwargs.get("date_from") is not None or call_kwargs[1].get("date_from") is not None


# ===========================================================================
# cmd_plan (exec_cmds)
# ===========================================================================


class TestCmdPlan:
    def test_no_intent_exits(self, tmp_path):
        kernel = _make_kernel()
        with pytest.raises(SystemExit) as exc_info:
            cmd_plan([], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_json_mode(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=True, output="plan output")
        kernel.run.return_value = result
        cmd_plan(["add OAuth2", "--json"], tmp_path, _factory(kernel))
        out = json.loads(capsys.readouterr().out)
        assert out["success"] is True

    def test_json_mode_failure_exits_1(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=False, errors=("plan failed",))
        kernel.run.return_value = result
        with pytest.raises(SystemExit) as exc_info:
            cmd_plan(["add OAuth2", "--json"], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_text_mode_success(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=True, output="planned everything")
        kernel.run.return_value = result
        cmd_plan(["add OAuth2"], tmp_path, _factory(kernel))
        out = capsys.readouterr().out
        assert "planned everything" in out

    def test_text_mode_failure(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=False, errors=("plan failed",))
        kernel.run.return_value = result
        with pytest.raises(SystemExit) as exc_info:
            cmd_plan(["add OAuth2"], tmp_path, _factory(kernel))
        assert exc_info.value.code == 1

    def test_run_mode(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=True, output="done")
        kernel.run.return_value = result
        cmd_plan(["add OAuth2", "--run"], tmp_path, _factory(kernel))
        kernel.run.assert_called_once()
        call_kwargs = kernel.run.call_args
        assert call_kwargs.kwargs.get("mode") == "plan-run" or call_kwargs[1].get("mode") == "plan-run"

    def test_debug_context_flag(self, tmp_path, capsys):
        kernel = _make_kernel()
        context = MagicMock()
        kernel.get_context.return_value = context
        result = RunResult(success=True, output="done")
        kernel.run.return_value = result
        cmd_plan(["add OAuth2", "--debug-context"], tmp_path, _factory(kernel))
        # Should not raise

    def test_intent_from_args(self, tmp_path, capsys):
        kernel = _make_kernel()
        result = RunResult(success=True, output="")
        kernel.run.return_value = result
        cmd_plan(["add", "OAuth2", "login"], tmp_path, _factory(kernel))
        call_args = kernel.run.call_args
        task = call_args.args[0]
        assert task.description == "add OAuth2 login"
        assert task.task_type == "plan"


# ===========================================================================
# Helper functions
# ===========================================================================


class TestHelperFunctions:
    def test_run_result_to_json(self):
        result = RunResult(success=True, output="ok", errors=("err1",))
        out = _run_result_to_json(result)
        assert out["success"] is True
        assert out["errors"] == ["err1"]
        assert "gates" in out

    def test_gates_json_empty(self):
        result = RunResult(success=True)
        out = _gates_json(result)
        assert out == {}

    def test_gates_json_with_gate(self):
        stage = StageSummary(
            name="quality_gate",
            status="success",
            details={"gate": {"status": "passed", "reason": "", "findings": []},
                      "policy": {}},
        )
        result = RunResult(success=True, stages=(stage,))
        out = _gates_json(result)
        assert "quality_gate" in out
        assert out["quality_gate"]["status"] == "passed"

    def test_gate_label_pass(self):
        stage = StageSummary(
            name="quality_gate",
            status="success",
            details={"gate": {"status": "passed"}, "policy": {}},
        )
        label, detail = _gate_label(stage)
        assert label == "PASS"

    def test_gate_label_fail(self):
        stage = StageSummary(
            name="quality_gate",
            status="failed",
            reason="lint errors",
            details={"gate": {"status": "failed", "reason": "lint errors"}, "policy": {}},
        )
        label, detail = _gate_label(stage)
        assert label == "FAIL"
        assert "lint errors" in detail

    def test_gate_label_skipped(self):
        stage = StageSummary(
            name="quality_gate",
            status="skipped",
            details={"gate": {"status": "skipped"}, "policy": {}},
        )
        label, detail = _gate_label(stage)
        assert label == "SKIP"
        assert "skipped" in detail

    def test_gate_label_overridden(self):
        stage = StageSummary(
            name="quality_gate",
            status="success",
            details={"gate": {"status": "passed"},
                      "policy": {"overridden": True, "override_reason": "manual"}},
        )
        label, detail = _gate_label(stage)
        assert label == "PASS"
        assert "override" in detail

    def test_gate_label_warn(self):
        stage = StageSummary(
            name="quality_gate",
            status="success",
            details={"gate": {"status": "passed"},
                      "policy": {"decision": "warn"}},
        )
        label, detail = _gate_label(stage)
        assert label == "PASS"
        assert "warn" in detail

    def test_render_plan_list_empty(self, capsys):
        _render_plan_list({})
        out = capsys.readouterr().out
        assert "No subtasks" in out

    def test_render_plan_list_with_subtasks(self, capsys):
        _render_plan_list({"subtasks": [{"description": "task 1"}, {"description": "task 2"}]})
        err = capsys.readouterr().err
        assert "2 tarefas" in err
        assert "task 1" in err
        assert "task 2" in err

    def test_render_stage_planner(self, capsys):
        stage = StageSummary(
            name="planner",
            status="success",
            details={"plan": {"subtasks": [{"description": "do stuff"}]}},
        )
        _render_stage(stage)
        err = capsys.readouterr().err
        assert "do stuff" in err

    def test_render_stage_developer_success(self, capsys):
        stage = StageSummary(
            name="developer:main",
            status="success",
            details={"description": "fix bug"},
        )
        _render_stage(stage)
        out = capsys.readouterr().out
        assert "✓" in out
        assert "fix bug" in out

    def test_render_stage_developer_failure(self, capsys):
        stage = StageSummary(
            name="developer:main",
            status="failed",
            details={"description": "fix bug"},
        )
        _render_stage(stage)
        out = capsys.readouterr().out
        assert "✗" in out

    def test_render_run_result_with_subtasks(self, capsys):
        result = RunResult(success=True, output="output", subtask_count=3, completed_count=2)
        _render_run_result(result)
        out = capsys.readouterr().out
        assert "2/3 tasks completed" in out

    def test_render_run_result_without_subtasks(self, capsys):
        result = RunResult(success=True, output="planned everything")
        _render_run_result(result)
        out = capsys.readouterr().out
        assert "planned everything" in out

    def test_render_gate_trail_no_gates(self, capsys):
        result = RunResult(success=True)
        _render_gate_trail(result)
        out = capsys.readouterr().out
        assert out == ""

    def test_render_gate_trail_with_gates(self, capsys):
        stage = StageSummary(
            name="quality_gate",
            status="success",
            details={"gate": {"status": "passed"}, "policy": {}},
        )
        result = RunResult(success=True, stages=(stage,))
        _render_gate_trail(result)
        err = capsys.readouterr().err
        assert "Quality Gates:" in err
        assert "quality_gate" in err
