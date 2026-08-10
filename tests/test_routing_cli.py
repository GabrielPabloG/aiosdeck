"""Tests for routing CLI — explain, stats, records."""

import json
from pathlib import Path

import pytest

from aios.routing.cli import (
    cmd_route,
    cmd_route_explain,
    cmd_route_stats,
    _parse_explain_args,
    _parse_stats_args,
)


class TestRouteExplain:
    def test_explain_planner_high(self, capsys):
        def fake_kernel(_path):
            class FakeConfigEngine:
                name = "config"

                def __init__(self):
                    self.config = type(
                        "C",
                        (),
                        {
                            "routing": type(
                                "R",
                                (),
                                {
                                    "enabled": True,
                                    "default_provider": "ollama",
                                    "default_model": "llama3",
                                    "default_variant": "",
                                    "rules": [
                                        {
                                            "agent": "planner",
                                            "complexity": "high",
                                            "provider": "anthropic",
                                            "model": "claude-sonnet",
                                        },
                                    ],
                                    "cost_cap": 0.0,
                                    "context_limits": {},
                                    "fallback_providers": [
                                        {"provider": "ollama", "model": "llama3"},
                                    ],
                                },
                            )()
                        },
                    )()

            class FakeKernel:
                def start(self):
                    pass

                def get_engine(self, name):
                    if name == "config":
                        return FakeConfigEngine()
                    return None

            return FakeKernel()

        cmd_route_explain(
            ["--agent", "planner", "--task-type", "plan", "--complexity", "high"],
            Path.cwd(),
            fake_kernel,
        )
        captured = capsys.readouterr()
        assert "anthropic/claude-sonnet" in captured.out
        assert "policy:0" in captured.out

    def test_explain_json_output(self, capsys):
        def fake_kernel(_path):
            class FakeConfigEngine:
                name = "config"

                def __init__(self):
                    self.config = type(
                        "C",
                        (),
                        {
                            "routing": type(
                                "R",
                                (),
                                {
                                    "enabled": True,
                                    "default_provider": "ollama",
                                    "default_model": "llama3",
                                    "default_variant": "",
                                    "rules": [],
                                    "cost_cap": 0.0,
                                    "context_limits": {},
                                    "fallback_providers": [
                                        {"provider": "ollama", "model": "llama3"},
                                    ],
                                },
                            )()
                        },
                    )()

            class FakeKernel:
                def start(self):
                    pass

                def get_engine(self, name):
                    if name == "config":
                        return FakeConfigEngine()
                    return None

            return FakeKernel()

        cmd_route_explain(
            ["--agent", "developer", "--json"],
            Path.cwd(),
            fake_kernel,
        )
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["model"] == "ollama/llama3"

    def test_parse_explain_args_defaults(self):
        args = _parse_explain_args(["--agent", "developer"])
        assert args["agent"] == "developer"
        assert args.get("task_type", "code") == "code"

    def test_parse_explain_args_full(self):
        args = _parse_explain_args(
            [
                "--agent",
                "planner",
                "--task-type",
                "plan",
                "--complexity",
                "high",
                "--context-size",
                "8000",
                "--json",
            ]
        )
        assert args["agent"] == "planner"
        assert args["task_type"] == "plan"
        assert args["complexity"] == "high"
        assert args["context_size"] == 8000
        assert args.get("json") is True


class TestRouteStats:
    def test_stats_json_output(self, capsys):
        def fake_kernel(_path):
            class FakeTelemetry:
                def query_routing_stats(self, **kwargs):
                    return [
                        {
                            "agent": "planner",
                            "model": "claude-sonnet",
                            "provider": "anthropic",
                            "routes": 10,
                            "fallbacks": 2,
                            "avg_estimated_cost": 0.15,
                            "avg_context_size": 8000,
                        },
                    ]

                def query_routing_records(self, **kwargs):
                    return []

                def query_route_accuracy(self, **kwargs):
                    return []

            class FakeKernel:
                def start(self):
                    pass

                def get_engine(self, name):
                    if name == "telemetry":
                        return FakeTelemetry()
                    return None

            return FakeKernel()

        cmd_route_stats(["--json"], Path.cwd(), fake_kernel)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 1
        assert data[0]["agent"] == "planner"

    def test_stats_records_text(self, capsys):
        def fake_kernel(_path):
            class FakeTelemetry:
                def query_routing_stats(self, **kwargs):
                    return []

                def query_routing_records(self, **kwargs):
                    return [
                        {
                            "agent": "planner",
                            "model": "claude-sonnet",
                            "reason": "policy:0",
                            "estimated_cost": 0.15,
                            "fallback_used": False,
                            "source": "router",
                            "timestamp": "2025-01-01T00:00:00",
                            "provider": "anthropic",
                            "task_type": "plan",
                            "complexity": "high",
                            "variant": "high",
                            "context_size": 8000,
                            "fallback_reason": "",
                            "correlation_id": "c1",
                        },
                    ]

                def query_route_accuracy(self, **kwargs):
                    return []

            class FakeKernel:
                def start(self):
                    pass

                def get_engine(self, name):
                    if name == "telemetry":
                        return FakeTelemetry()
                    return None

            return FakeKernel()

        cmd_route_stats(["--records"], Path.cwd(), fake_kernel)
        captured = capsys.readouterr()
        assert "claude-sonnet" in captured.out
        assert "policy:0" in captured.out

    def test_stats_accuracy(self, capsys):
        def fake_kernel(_path):
            class FakeTelemetry:
                def query_routing_stats(self, **kwargs):
                    return []

                def query_routing_records(self, **kwargs):
                    return []

                def query_route_accuracy(self, **kwargs):
                    return [
                        {
                            "agent": "planner",
                            "model": "claude-sonnet",
                            "estimated_cost": 0.15,
                            "actual_cost": 0.18,
                            "delta": 0.03,
                            "correlation_id": "c1",
                            "timestamp": "2025-01-01T00:00:00",
                        },
                    ]

            class FakeKernel:
                def start(self):
                    pass

                def get_engine(self, name):
                    if name == "telemetry":
                        return FakeTelemetry()
                    return None

            return FakeKernel()

        cmd_route_stats(["--accuracy"], Path.cwd(), fake_kernel)
        captured = capsys.readouterr()
        assert "claude-sonnet" in captured.out
        assert "est=" in captured.out
        assert "act=" in captured.out

    def test_parse_stats_args_records(self):
        args = _parse_stats_args(["--records", "--agent", "planner", "--limit", "50"])
        assert args["records"] is True
        assert args["agent"] == "planner"
        assert args["limit"] == 50

    def test_parse_stats_args_accuracy(self):
        args = _parse_stats_args(["--accuracy", "--json"])
        assert args["accuracy"] is True
        assert args["json"] is True


class TestCmdRoute:
    def test_no_subcommand_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_route([], Path.cwd(), lambda p: None)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: aios route" in captured.err
        assert "explain" in captured.out
        assert "stats" in captured.out

    def test_unknown_subcommand_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_route(["bogus"], Path.cwd(), lambda p: None)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Unknown subcommand: bogus" in captured.err
