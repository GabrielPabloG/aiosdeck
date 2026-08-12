"""Tests for the versioned benchmark schema (Issue #35).

``results[]`` is the single canonical representation of benchmark output.
No parallel ``phases``/``commands``/``startup`` structures survive at the
top level of a report. All tests drive the CLI entry point with a stub
kernel factory so no runtime/model is required.
"""

import json
from unittest.mock import MagicMock

import pytest

from aios.cli.commands.benchmark import cmd_benchmark
from aios.telemetry.schema import (
    METRICS,
    REQUIRED_KEYS,
    SCHEMA_VERSION,
    validate_report,
)


def _run(value: float = 10.0) -> dict:
    return {
        "wall_time_ms": value,
        "cpu_user_ms": value,
        "cpu_system_ms": value,
        "peak_memory_kb": value,
    }


def _summary(value: float = 10.0) -> dict:
    return {
        "count": 1,
        "min": value,
        "max": value,
        "mean": value,
        "p50": value,
        "p95": value,
        "p99": value,
        "samples": [value],
    }


def _result(target: str = "doctor", **overrides) -> dict:
    result = {
        "group": "commands",
        "target": target,
        "runs": [_run()],
        "summaries": {metric: _summary() for metric in METRICS},
    }
    result.update(overrides)
    return result


def _valid_report(**overrides) -> dict:
    report = {
        "schema_version": SCHEMA_VERSION,
        "aiosdeck_version": "1.0.0",
        "git_commit": "abc123",
        "timestamp": "2026-08-11T00:00:00+00:00",
        "system_info": {"platform": "linux", "python": "3.12"},
        "results": [_result()],
    }
    report.update(overrides)
    return report


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


class TestSystemInfo:
    def test_system_info_exposes_environment_provenance(self):
        from aios.telemetry.schema import system_info

        info = system_info()
        for key in (
            "system",
            "platform",
            "machine",
            "python",
            "distro",
            "kernel",
            "cpu",
            "cpu_count",
            "memory_mb",
        ):
            assert key in info, f"system_info missing {key!r}"
        assert info["cpu_count"] >= 1
        assert info["memory_mb"] > 0


class TestSchemaValidation:
    def test_benchmark_schema_validation(self):
        assert validate_report(_valid_report()) == []

    def test_benchmark_schema_version_mismatch_rejected(self):
        report = _valid_report(schema_version="0.9")
        errors = validate_report(report)
        assert any("schema_version" in error for error in errors)

    def test_schema_requires_all_top_level_keys(self):
        for key in REQUIRED_KEYS:
            report = _valid_report()
            del report[key]
            errors = validate_report(report)
            assert any(f"missing top-level key: {key}" in error for error in errors)

    def test_schema_rejects_unknown_metric(self):
        report = _valid_report()
        report["results"][0]["runs"][0]["gpu_time_ms"] = 5.0
        errors = validate_report(report)
        assert any("unknown key" in error for error in errors)


class TestValidateCli:
    def test_validate_cli_accepts_good_file(self, tmp_path, capsys):
        path = tmp_path / "report.json"
        path.write_text(json.dumps(_valid_report()))
        with pytest.raises(SystemExit) as exc:
            cmd_benchmark(["validate", str(path)], tmp_path, MagicMock())
        assert exc.value.code == 0
        assert "Valid" in capsys.readouterr().out

    def test_validate_cli_rejects_bad_file(self, tmp_path, capsys):
        path = tmp_path / "report.json"
        path.write_text(json.dumps(_valid_report(schema_version="0.9")))
        with pytest.raises(SystemExit) as exc:
            cmd_benchmark(["validate", str(path)], tmp_path, MagicMock())
        assert exc.value.code == 1
        assert "Invalid" in capsys.readouterr().out


class TestBenchmarkOutput:
    def test_benchmark_output_matches_schema(self, tmp_path, capsys):
        cmd_benchmark(
            ["phases", "--json", "--warmup", "0", "--repeat", "1"], tmp_path, _StubKernelFactory()
        )
        out = json.loads(capsys.readouterr().out)
        assert validate_report(out) == []

    def test_peak_memory_kb_present_in_each_run(self, tmp_path, capsys):
        cmd_benchmark(
            ["all", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        results = [r for r in out["results"] if not r.get("skipped")]
        assert results
        for result in results:
            for run in result["runs"]:
                assert "peak_memory_kb" in run
                assert run["peak_memory_kb"] > 0

    def test_report_has_no_parallel_structures(self, tmp_path, capsys):
        cmd_benchmark(
            ["all", "--json", "--warmup", "0", "--repeat", "1", "--skip-agents"],
            tmp_path,
            _StubKernelFactory(),
        )
        out = json.loads(capsys.readouterr().out)
        for forbidden in ("phases", "commands", "startup"):
            assert forbidden not in out
        assert isinstance(out["results"], list)
        assert len(out["results"]) > 0
