"""Tests for the aios benchmark command (Fase 0 — Instrumentação, v1.1.0).

The benchmark measures wall/CPU times with time.monotonic() + os.times() for
startup phases and CLI commands, reporting p50/p95/p99 percentiles and
preserving raw runs. All tests drive the CLI entry point with a stub kernel
factory so no runtime/model is required.

The report's canonical shape is a flat ``results[]`` list (versioned schema
v1). Tests walk ``results[]`` — never top-level ``phases``/``commands``
structures.
"""

import json
from unittest.mock import MagicMock, patch

from aios import __version__
from aios.cli.commands.benchmark import _collect_samples, cmd_benchmark
from aios.routing.models import RouteDecision, RouteInput
from aios.telemetry.benchmark import (
    BARE_PROMPT,
    METRICS,
    PHASES,
    _run_bare_probe,
    baseline_path,
    measure_lifecycle,
    percentile,
    summarize,
)
from aios.telemetry.schema import SCHEMA_VERSION, validate_report

ALL_COMMANDS = ("dashboard", "doctor", "skills", "memory", "plan", "backlog")


def _result(report: dict, group: str, target: str) -> dict:
    for result in report["results"]:
        if result.get("group") == group and result["target"] == target:
            return result
    raise KeyError((group, target))


def _group(report: dict, group: str) -> dict[str, dict]:
    return {r["target"]: r for r in report["results"] if r.get("group") == group}


class _StubKernelFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.kernel = _stub_kernel()

    def __call__(self, project_path):
        self.calls += 1
        return self.kernel


def _stub_kernel():
    kernel = MagicMock()
    kernel.start = MagicMock()
    kernel.shutdown = MagicMock()
    kernel.get_context = MagicMock(return_value=MagicMock())
    kernel.run = MagicMock()
    kernel.run_agent = MagicMock()
    runtime = MagicMock()
    runtime.router = None
    kernel.get_engine = MagicMock(return_value=runtime)
    return kernel


class _FakeRouter:
    """Deterministic router that returns a per-agent model decision."""

    def __init__(self, by_agent: dict[str, str]) -> None:
        self.by_agent = dict(by_agent)
        self.inputs: list[RouteInput] = []

    def route(self, input: RouteInput) -> RouteDecision:
        self.inputs.append(input)
        model = self.by_agent.get(input.agent, "ollama/llama3")
        provider, _, _ = model.partition("/")
        return RouteDecision(provider=provider or "ollama", model=model, reason="test")


class TestBenchmarkProfile:
    def _profiled_kernel(self):
        kernel = _stub_kernel()
        kernel.timings = {
            "kernel_start_total_ms": 12.5,
            "engines": {"config_init_ms": 1.0, "context_init_ms": 2.0},
            "context_detectors": {"git_ms": 0.5, "docker_ms": 1.0},
        }
        return kernel

    def test_profile_flag_parsing(self):
        from aios.cli.commands.benchmark import _parse_args

        assert _parse_args(["phases", "--profile"])["profile"] is True
        assert _parse_args(["phases"])["profile"] is False

    def test_report_includes_timings_and_passes_validate_report(self, tmp_path, capsys):
        factory = lambda project_path: self._profiled_kernel()  # noqa: E731
        cmd_benchmark(
            ["phases", "--profile", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            factory,
        )
        out = json.loads(capsys.readouterr().out)
        assert validate_report(out) == []
        kernel_init = _result(out, "phases", "kernel_init")
        assert "timings" in kernel_init["runs"][0]
        assert kernel_init["runs"][0]["timings"]["kernel_start_total_ms"] == 12.5
        assert "engines" in kernel_init["runs"][0]["timings"]

    def test_timings_absent_when_profile_off(self, tmp_path, capsys):
        factory = lambda project_path: self._profiled_kernel()  # noqa: E731
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            factory,
        )
        out = json.loads(capsys.readouterr().out)
        kernel_init = _result(out, "phases", "kernel_init")
        assert "timings" not in kernel_init["runs"][0]
        assert validate_report(out) == []

    def test_measure_lifecycle_profile_restores_env(self):
        kernel = _stub_kernel()
        kernel.timings = {"kernel_start_total_ms": 1.0, "engines": {}, "context_detectors": {}}
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True, profile=True)
        assert result["kernel_init"]["timings"]["kernel_start_total_ms"] == 1.0
        import os

        assert os.environ.get("AIOS_PROFILE") is None


class TestPercentile:
    def test_single_value(self):
        assert percentile([5.0], 50) == 5.0

    def test_sorted_input_median(self):
        assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0

    def test_interpolates_between_points(self):
        assert percentile([0.0, 10.0], 50) == 5.0

    def test_p95_and_p99(self):
        data = list(range(1, 101))
        p95 = percentile(sorted(data), 95)
        p99 = percentile(sorted(data), 99)
        assert 95.0 <= p95 < 96.0
        assert 99.0 <= p99 < 100.0
        assert p95 <= p99

    def test_empty_returns_zero(self):
        assert percentile([], 50) == 0.0


class TestSummarize:
    def test_metrics(self):
        s = summarize([1.0, 2.0, 3.0])
        assert s["count"] == 3
        assert s["min"] == 1.0
        assert s["max"] == 3.0
        assert s["mean"] == 2.0
        assert s["p50"] == 2.0
        assert s["p50"] <= s["p95"] <= s["p99"]
        assert s["samples"] == [1.0, 2.0, 3.0]

    def test_empty(self):
        s = summarize([])
        assert s["count"] == 0
        assert s["p50"] is None
        assert s["samples"] == []

    def test_keeps_raw_samples_in_order(self):
        samples = [3.0, 1.0, 2.0]
        s = summarize(samples)
        assert s["samples"] == samples


class TestBenchmarkCli:
    def test_benchmark_no_target_shows_targets(self, tmp_path, capsys):
        cmd_benchmark([], tmp_path, _StubKernelFactory())
        out = capsys.readouterr().out
        for target in (
            "all",
            "startup",
            "phases",
            "validate",
            "dashboard",
            "doctor",
            "skills",
            "memory",
            "plan",
            "backlog",
        ):
            assert target in out
        for option in (
            "--json",
            "--warmup",
            "--repeat",
            "--output",
            "--skip-agents",
            "--process",
            "--profile",
            "--bare-task",
        ):
            assert option in out

    def test_benchmark_help_flag_shows_targets(self, tmp_path, capsys):
        for flag in ("--help", "-h"):
            capsys.readouterr()
            cmd_benchmark([flag], tmp_path, _StubKernelFactory())
            out = capsys.readouterr().out
            assert "all" in out
            assert "phases" in out
            assert "--warmup" in out
            assert "--repeat" in out

    def test_benchmark_phases_target_profiles_lifecycle(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "2"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        for phase in PHASES:
            entry = _result(out, "phases", phase)
            assert entry["summaries"]["wall_time_ms"]["p50"] > 0

    def test_benchmark_cli_outputs_json(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "2"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        assert out["schema_version"] == SCHEMA_VERSION
        assert out["aiosdeck_version"] == __version__
        assert "results" in out
        assert _result(out, "phases", "startup")["summaries"]["wall_time_ms"]["p50"] > 0

    def test_benchmark_reports_runtime_info(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("AIOS_DEFAULT_MODEL", "ollama")
        monkeypatch.setenv("AIOS_OLLAMA_MODEL", "llama3.2")
        monkeypatch.setenv("AIOS_OLLAMA_HOST", "http://localhost:11434")
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        assert out["runtime_info"] == {
            "provider": "ollama",
            "model": "llama3.2",
            "host": "http://localhost:11434",
        }

    def test_benchmark_measures_startup_time(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "2"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        startup = _result(out, "phases", "startup")
        assert startup["summaries"]["wall_time_ms"]["p50"] > 0
        assert len(startup["runs"]) == 2

    def test_benchmark_all_commands_run(self, tmp_path, capsys):
        cmd_benchmark(
            ["all", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        commands = _group(out, "commands")
        assert set(commands) == set(ALL_COMMANDS)
        for name in ALL_COMMANDS:
            entry = commands[name]
            assert "runs" in entry
            assert entry["summaries"]["wall_time_ms"]["count"] == 1

    def test_benchmark_repeat_produces_reliable_data(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "5"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        for phase in PHASES:
            entry = _result(out, "phases", phase)
            assert len(entry["runs"]) == 5
            summary = entry["summaries"]["wall_time_ms"]
            assert summary["count"] == 5
            assert summary["p50"] <= summary["p95"] <= summary["p99"]

    def test_benchmark_warmup_discards_cold_runs(self, tmp_path, capsys):
        factory = _StubKernelFactory()
        cmd_benchmark(["phases", "--json", "--warmup", "2", "--repeat", "3"], tmp_path, factory)
        out = json.loads(capsys.readouterr().out)
        startup = _result(out, "phases", "startup")
        assert len(startup["runs"]) == 3
        assert startup["summaries"]["wall_time_ms"]["count"] == 3
        assert factory.calls == 5

    def test_each_measurement_captures_wall_and_cpu_times(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        run = _result(out, "phases", "startup")["runs"][0]
        assert set(METRICS) == {
            "wall_time_ms",
            "cpu_user_ms",
            "cpu_system_ms",
            "peak_memory_kb",
        }
        for metric in METRICS:
            assert metric in run
            assert run[metric] >= 0

    def test_skip_agents_marks_plan_phases_skipped(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "phases", "plan")["skipped"] is True
        assert _result(out, "phases", "agent_exec")["skipped"] is True
        assert "runs" not in _result(out, "phases", "plan")
        assert "runs" in _result(out, "phases", "startup")

    def test_skip_agents_skips_plan_and_backlog_commands(self, tmp_path, capsys):
        cmd_benchmark(
            ["all", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "commands", "plan")["skipped"] is True
        assert _result(out, "commands", "backlog")["skipped"] is True
        assert "runs" in _result(out, "commands", "doctor")

    def test_output_writes_baseline_file(self, tmp_path, capsys):
        baseline = tmp_path / "benchmarks" / "v1.0.0.json"
        cmd_benchmark(
            ["all", "--json", "--warmup", "0", "--repeat", "1", "--output", str(baseline)],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert out["output"] == str(baseline)
        assert baseline.exists()
        saved = json.loads(baseline.read_text())
        assert saved["schema_version"] == SCHEMA_VERSION
        assert "results" in saved

    def test_minimal_mode_without_kernel(self, tmp_path, capsys):
        def broken_factory(project_path):
            raise RuntimeError("no kernel available")

        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, broken_factory
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "phases", "startup")["runs"][0]["error"] == "no kernel available"
        assert _result(out, "phases", "kernel_init")["runs"][0]["error"] == "kernel unavailable"

    def test_command_error_records_timing(self, tmp_path, capsys):
        kernel = _stub_kernel()
        engine = MagicMock()
        engine.list_boards.side_effect = RuntimeError("boom")
        kernel.get_engine = MagicMock(return_value=engine)
        factory = lambda project_path: kernel  # noqa: E731
        cmd_benchmark(["backlog", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, factory)
        out = json.loads(capsys.readouterr().out)
        entry = _result(out, "commands", "backlog")
        run = entry["runs"][0]
        assert "error" in run
        assert run["wall_time_ms"] >= 0
        assert entry["errors"] == 1

    def test_unknown_command_reports_available(self, tmp_path):
        from aios.cli.commands.benchmark import _AVAILABLE

        assert "all" in _AVAILABLE
        assert "validate" in _AVAILABLE
        assert set(ALL_COMMANDS) <= set(_AVAILABLE)

    def test_startup_process_mode(self, tmp_path, capsys):
        cmd_benchmark(
            ["startup", "--process", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        startup = _result(out, "startup", "startup")
        assert startup["mode"] == "process"
        assert startup["summaries"]["wall_time_ms"]["count"] == 1

    def test_collect_samples_reports_progress_to_stderr(self, capsys):
        calls: list[str] = []

        def run_once() -> dict:
            calls.append("x")
            return {"wall_time_ms": 1.0, "cpu_user_ms": 0.0, "cpu_system_ms": 0.0}

        _collect_samples(run_once, {"warmup": 1, "repeat": 2}, label="phases")
        err = capsys.readouterr().err
        assert "phases" in err
        assert "warmup 1/1" in err
        assert "1/2" in err
        assert "2/2" in err
        assert len(calls) == 3

    def test_collect_samples_progress_does_not_touch_stdout(self, capsys):
        def run_once() -> dict:
            return {"wall_time_ms": 1.0, "cpu_user_ms": 0.0, "cpu_system_ms": 0.0}

        _collect_samples(run_once, {"warmup": 0, "repeat": 1}, label="doctor")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "1/1" in captured.err

    def test_collect_samples_no_label_omits_prefix(self, capsys):
        def run_once() -> dict:
            return {"wall_time_ms": 1.0, "cpu_user_ms": 0.0, "cpu_system_ms": 0.0}

        _collect_samples(run_once, {"warmup": 0, "repeat": 1}, label="")
        err = capsys.readouterr().err
        assert "1/1" in err

    def test_measure_lifecycle_reports_phase_start_end(self):
        calls: list[tuple] = []

        def _on_phase(event):
            calls.append(event)

        kernel = MagicMock()
        kernel.start = MagicMock()
        kernel.get_context = MagicMock(return_value=None)
        kernel.run = MagicMock(return_value=MagicMock(success=True))
        kernel.run_agent = MagicMock(return_value=MagicMock(success=True))
        kernel.shutdown = MagicMock()

        measure_lifecycle(
            ".",
            lambda _: kernel,
            skip_agents=False,
            on_phase=_on_phase,
        )

        assert any(c == ("plan", "start") for c in calls)
        assert any(c[0] == "plan" and c[1] == "end" for c in calls)
        assert any(c == ("agent_exec", "start") for c in calls)
        assert any(c[0] == "agent_exec" and c[1] == "end" for c in calls)

    def test_measure_lifecycle_no_on_phase_defaults(self):
        kernel = MagicMock()
        kernel.start = MagicMock()
        kernel.get_context = MagicMock(return_value=None)
        kernel.run = MagicMock(return_value=MagicMock(success=True))
        kernel.run_agent = MagicMock(return_value=MagicMock(success=True))
        kernel.shutdown = MagicMock()

        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False)
        assert "plan" in result
        assert "agent_exec" in result

    def test_phases_bar_shows_sample_and_phase(self, tmp_path, capsys):
        with patch("aios.cli.commands.benchmark.ProgressBar") as mock_bar_cls:
            mock_bar = MagicMock()
            mock_bar_cls.return_value = mock_bar

            cmd_benchmark(
                ["phases", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
                tmp_path,
                lambda _: _stub_kernel(),
            )

        assert mock_bar_cls.called

    def test_phases_bar_json_stdout_clean(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
            tmp_path,
            lambda _: _stub_kernel(),
        )
        out_text = capsys.readouterr().out
        report = json.loads(out_text)
        assert "schema_version" in report
        assert "results" in report
        assert out_text.strip().startswith("{")


class TestBenchmarkBareTask:
    def test_bare_task_flag_parsing(self):
        from aios.cli.commands.benchmark import _parse_args

        assert _parse_args(["phases", "--bare-task"])["bare_task"] is True
        assert _parse_args(["phases"])["bare_task"] is False

    def test_benchmark_bare_task_uses_restricted_task(self, tmp_path, capsys):
        kernel = _stub_kernel()
        runtime = kernel.get_engine.return_value
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            lambda _: kernel,
        )
        json.loads(capsys.readouterr().out)
        assert runtime.execute.called
        prompt, skills, capabilities = runtime.execute.call_args.args
        assert skills == []
        assert capabilities == []
        permissions = runtime.execute.call_args.kwargs["permissions"]
        assert permissions.allowed == frozenset()
        assert prompt == BARE_PROMPT

    def test_phases_bare_task_skips_agent(self, tmp_path, capsys):
        kernel = _stub_kernel()
        runtime = kernel.get_engine.return_value
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            lambda _: kernel,
        )
        json.loads(capsys.readouterr().out)
        kernel.run.assert_not_called()
        kernel.run_agent.assert_not_called()
        assert runtime.execute.call_count == 2

    def test_bare_task_measures_plan_phases(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        for phase in ("plan", "agent_exec"):
            entry = _result(out, "phases", phase)
            assert "runs" in entry
            assert entry["summaries"]["wall_time_ms"]["p50"] > 0

    def test_bare_task_sets_mode_metadata(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert out["benchmark_mode"] == "bare"
        assert out["task_prompt_type"] == "restricted_ok"
        for phase in ("plan", "agent_exec"):
            entry = _result(out, "phases", phase)
            assert entry["tool_calls_count"] == 0
            assert entry["is_read_only"] is True

    def test_full_mode_keeps_default_metadata(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert out["benchmark_mode"] == "full"
        assert out["task_prompt_type"] == "full_task"
        for phase in ("plan", "agent_exec"):
            assert "tool_calls_count" not in _result(out, "phases", phase)
            assert "is_read_only" not in _result(out, "phases", phase)

    def test_bare_task_report_passes_schema(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "2"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert validate_report(out) == []

    def test_baseline_path_bare_suffix(self, tmp_path):
        assert baseline_path(tmp_path).name == f"v{__version__}.json"
        assert baseline_path(tmp_path, bare=True).name == f"v{__version__}-bare.json"


class TestBareRoutingParity:
    """Full and bare must resolve the model from the same per-phase router
    decision — an agent-specific routing rule can never diverge them."""

    def _bare_kernel_with_router(self):
        kernel = _stub_kernel()
        runtime = kernel.get_engine.return_value
        runtime.router = _FakeRouter({"planner": "ollama/model-b", "developer": "ollama/model-a"})
        return kernel, runtime

    def test_bare_model_matches_router_decision_for_phase(self):
        kernel, runtime = self._bare_kernel_with_router()
        _run_bare_probe(kernel, "plan")
        assert runtime.execute.call_args.kwargs["model"] == "ollama/model-b"
        _run_bare_probe(kernel, "agent_exec")
        assert runtime.execute.call_args.kwargs["model"] == "ollama/model-a"

    def test_bare_probe_builds_phase_route_input(self):
        kernel, runtime = self._bare_kernel_with_router()
        router = runtime.router
        _run_bare_probe(kernel, "plan")
        _run_bare_probe(kernel, "agent_exec")
        plan_input = router.inputs[0]
        agent_input = router.inputs[1]
        assert plan_input.agent == "planner"
        assert plan_input.task_type == "plan"
        assert agent_input.agent == "developer"
        assert agent_input.task_type == "code"

    def test_bare_uses_agent_specific_routing_rule(self, tmp_path, capsys):
        kernel, _ = self._bare_kernel_with_router()
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            lambda _: kernel,
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "phases", "plan")["model"] == "ollama/model-b"
        assert _result(out, "phases", "agent_exec")["model"] == "ollama/model-a"

    def test_full_records_effective_model(self, tmp_path, capsys):
        kernel, _ = self._bare_kernel_with_router()
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            lambda _: kernel,
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "phases", "plan")["model"] == "ollama/model-b"
        assert _result(out, "phases", "agent_exec")["model"] == "ollama/model-a"

    def test_model_empty_when_no_router(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--bare-task", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert _result(out, "phases", "plan")["model"] == ""
        assert _result(out, "phases", "agent_exec")["model"] == ""
        assert validate_report(out) == []

    def test_report_never_leaks_models_channel(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        assert "_models" not in out
        for result in out["results"]:
            assert "_models" not in result
