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
from unittest.mock import MagicMock

from aios.cli.commands.benchmark import cmd_benchmark
from aios.telemetry.benchmark import (
    METRICS,
    PHASES,
    percentile,
    summarize,
)
from aios.telemetry.schema import SCHEMA_VERSION

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
    kernel.get_engine = MagicMock(return_value=MagicMock())
    return kernel


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
        for option in ("--json", "--warmup", "--repeat", "--output", "--skip-agents", "--process"):
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
        assert out["aiosdeck_version"] == "1.0.0"
        assert "results" in out
        assert _result(out, "phases", "startup")["summaries"]["wall_time_ms"]["p50"] > 0

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
