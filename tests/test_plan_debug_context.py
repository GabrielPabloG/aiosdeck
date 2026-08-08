"""Tests for `aios plan --debug-context` — layer tree inspection."""

import aios.knowledge  # noqa: F401  (load before selector to avoid circular import)

import io
import sys
from unittest.mock import MagicMock

from aios.cli.commands import _cmd_plan
from aios.context.assembly import assemble_layers
from aios.context.cli import render_layer_tree
from aios.context.layers import Layer, LayerType
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.run_result import RunResult


def _make_context() -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _make_assembly():
    layers = [
        Layer(type=LayerType.TASK, content="Add login", source="task", guardrail=True, tokens=2),
        Layer(type=LayerType.PROJECT, content="Language: python", source="packet", tokens=2),
    ]
    return assemble_layers(layers, budget_total=100)


def _make_kernel() -> MagicMock:
    kernel = MagicMock()
    kernel.run.return_value = RunResult(
        success=True,
        plan={"goal": "x", "subtasks": []},
        output="{}",
        subtask_count=0,
        completed_count=0,
    )
    kernel.get_context.return_value = _make_context()
    knowledge = MagicMock()
    selection = MagicMock()
    selection.chunks = []
    knowledge.retrieve.return_value = selection
    kernel.get_engine.return_value = knowledge
    return kernel


class TestRenderLayerTree:
    def test_text_tree_contains_layer_types(self):
        out = render_layer_tree(_make_assembly(), as_json=False)
        assert "task" in out
        assert "project" in out
        assert "guardrail" in out

    def test_json_roundtrip(self):
        out = render_layer_tree(_make_assembly(), as_json=True)
        assert '"total_tokens"' in out
        assert '"layers"' in out


class TestCmdPlanDebugContext:
    def test_debug_context_prints_layer_tree(self):
        kernel = _make_kernel()

        stdout = io.StringIO()
        with __import__("pytest").MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--debug-context", "add login"], MagicMock(), lambda _: kernel)

        out = stdout.getvalue()
        assert "Context Layers" in out
        assert "planner" in out

    def test_debug_context_still_runs_kernel(self):
        kernel = _make_kernel()

        _cmd_plan(["--debug-context", "add login"], MagicMock(), lambda _: kernel)

        assert kernel.run.call_count == 1
        assert kernel.run.call_args.kwargs["mode"] == "plan"

    def test_normal_plan_unchanged(self):
        kernel = _make_kernel()

        stdout = io.StringIO()
        with __import__("pytest").MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["add login"], MagicMock(), lambda _: kernel)

        assert "Context Layers" not in stdout.getvalue()
        kernel.get_engine.assert_not_called()

    def test_debug_context_json(self):
        kernel = _make_kernel()

        stdout = io.StringIO()
        with __import__("pytest").MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--debug-context", "--json", "add login"], MagicMock(), lambda _: kernel)

        assert '"budget_tokens"' in stdout.getvalue()

    def test_debug_context_flag_not_part_of_intent(self):
        kernel = _make_kernel()

        _cmd_plan(["--debug-context", "add login"], MagicMock(), lambda _: kernel)

        task_arg = kernel.run.call_args[0][0]
        assert task_arg.description == "add login"
