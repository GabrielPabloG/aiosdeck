"""Tests for `aios benchmark compare` (#59).

The compare command confronts a baseline report against a current report
(kindled, or freshly measured in live mode) and classifies each matched
``(group, target)`` as Core vs Runtime-dependent.

Exit-code contract (precedence 2 > 1 > 0):
- 0 — no Core regression, environment compatible
- 1 — Core regression above threshold
- 2 — environment/runtime divergence (regressions measured in an
  incompatible environment are never reported as real)

Pure comparison logic lives in ``aios.telemetry.compare``; the CLI dispatch
(cmd_benchmark) only wires files/live runs into it. All tests drive the CLI
entry point with a stub kernel factory so no runtime/model is required.
"""

import json

import pytest

from aios import __version__
from aios.cli.commands.benchmark import cmd_benchmark
from aios.telemetry.benchmark import summarize_runs
from aios.telemetry.compare import (
    DEFAULT_THRESHOLD_PCT,
    RUNTIME_DEPENDENT,
    category_for,
    compare_reports,
)
from aios.telemetry.schema import SCHEMA_VERSION, system_info, validate_report

_METRICS_ZERO = {"cpu_user_ms": 0.0, "cpu_system_ms": 0.0, "peak_memory_kb": 0.0}


def _make_report(results, *, system=None, runtime=None, git="abc1234"):
    return {
        "schema_version": SCHEMA_VERSION,
        "aiosdeck_version": __version__,
        "git_commit": git,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "system_info": system or _system(),
        "runtime_info": runtime
        or {"provider": "ollama", "model": "llama3.2", "host": "http://localhost:11434"},
        "results": results,
    }


def _system(**overrides):
    base = system_info()
    return {**base, **overrides}


def _result(group, target, samples):
    runs = [{"wall_time_ms": s, **_METRICS_ZERO} for s in samples]
    return {"group": group, "target": target, "runs": runs, "summaries": summarize_runs(runs)}


def _core_results(p50=100.0):
    return [
        _result("phases", "startup", [p50]),
        _result("phases", "kernel_init", [p50]),
        _result("phases", "context_load", [p50]),
        _result("phases", "skill_load", [p50]),
        _result("phases", "telemetry_flush", [p50]),
    ]


def _runtime_results(p50=100.0):
    return [
        _result("phases", "plan", [p50]),
        _result("phases", "agent_exec", [p50]),
    ]


class _StubKernelFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, project_path):
        self.calls += 1
        from tests.test_benchmark import _stub_kernel  # noqa: PLC0415

        return _stub_kernel()


def _find(report, group, target):
    for result in report["results"]:
        if result.get("group") == group and result["target"] == target:
            return result
    raise KeyError((group, target))


class TestCompareCore:
    def test_compare_exit_zero_no_regression(self):
        baseline = _make_report(_core_results(100.0) + _runtime_results(100.0))
        current = _make_report(_core_results(100.0) + _runtime_results(100.0))
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 0
        assert report["compare"]["core_regressions"] == []
        assert report["compare"]["runtime_warnings"] == []

    def test_compare_core_regression_exit_one(self):
        baseline = _make_report(_core_results(100.0) + _runtime_results(100.0))
        current = _make_report(_core_results(130.0) + _runtime_results(100.0))
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 1
        assert report["compare"]["core_regressions"]
        for result in report["results"]:
            if result.get("category") == "core":
                assert result["verdict"] == "regression"

    def test_compare_runtime_regression_warns_not_fails(self):
        baseline = _make_report(_core_results(100.0) + _runtime_results(100.0))
        current = _make_report(_core_results(100.0) + _runtime_results(150.0))
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 0
        assert report["compare"]["runtime_warnings"]
        assert report["compare"]["core_regressions"] == []
        assert _find(report, "phases", "plan")["verdict"] == "warning"


class TestCompareEnvironment:
    def test_compare_env_divergence_exit_two_and_precedence(self):
        baseline = _make_report(
            _core_results(100.0) + _runtime_results(100.0),
            system=_system(cpu_count=8, distro="Ubuntu 24.04"),
        )
        current = _make_report(
            _core_results(100.0) + _runtime_results(100.0),
            system=_system(cpu_count=4, distro="Fedora 40"),
        )
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 2
        assert sorted(report["compare"]["env_divergence"]) == ["cpu_count", "distro"]

        regressed = _make_report(
            _core_results(130.0) + _runtime_results(100.0),
            system=_system(cpu_count=4, distro="Fedora 40"),
        )
        report = compare_reports(baseline, regressed)
        assert report["compare"]["exit_code"] == 2
        assert report["compare"]["core_regressions"]

    def test_compare_runtime_divergence_exit_two(self):
        baseline = _make_report(
            _core_results(100.0),
            runtime={"provider": "ollama", "model": "llama3.2", "host": "http://a:11434"},
        )
        current = _make_report(
            _core_results(100.0),
            runtime={"provider": "ollama", "model": "llama3.1", "host": "http://b:11434"},
        )
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 2
        assert sorted(report["compare"]["runtime_divergence"]) == ["host", "model"]


class TestCompareThreshold:
    def test_compare_threshold_rebases_delta(self):
        baseline = _make_report(_core_results(100.0) + _runtime_results(100.0))
        current = _make_report(_core_results(120.0) + _runtime_results(100.0))
        assert DEFAULT_THRESHOLD_PCT == 10.0
        assert compare_reports(baseline, current)["compare"]["exit_code"] == 1
        report = compare_reports(baseline, current, threshold=25.0)
        assert report["compare"]["exit_code"] == 0
        assert report["compare"]["threshold_pct"] == 25.0

    def test_compare_threshold_flag_cli(self, tmp_path, capsys):
        bpath = tmp_path / "base.json"
        cpath = tmp_path / "cur.json"
        bpath.write_text(json.dumps(_make_report(_core_results(100.0))))
        cpath.write_text(json.dumps(_make_report(_core_results(120.0))))
        with pytest.raises(SystemExit) as error:
            cmd_benchmark(["compare", str(bpath), str(cpath), "--threshold", "25"], tmp_path, None)
        assert error.value.code == 0
        capsys.readouterr()


class TestCompareMissing:
    def test_compare_missing_target_skipped(self):
        baseline = _make_report(
            _core_results(100.0)
            + _runtime_results(100.0)
            + [_result("commands", "dashboard", [100.0])]
        )
        current = _make_report(_core_results(100.0) + _runtime_results(100.0))
        report = compare_reports(baseline, current)
        assert report["compare"]["exit_code"] == 0
        assert report["compare"]["core_regressions"] == []
        skipped = [r for r in report["results"] if r.get("skipped")]
        assert any(r["target"] == "dashboard" for r in skipped)


class TestCompareCli:
    def test_compare_json_passes_validate(self, tmp_path, capsys):
        baseline = _make_report(_core_results(100.0) + _runtime_results(100.0))
        current = _make_report(_core_results(100.0) + _runtime_results(100.0))
        bpath = tmp_path / "base.json"
        cpath = tmp_path / "cur.json"
        bpath.write_text(json.dumps(baseline))
        cpath.write_text(json.dumps(current))
        with pytest.raises(SystemExit) as error:
            cmd_benchmark(["compare", str(bpath), str(cpath), "--json"], tmp_path, None)
        assert error.value.code == 0
        out = json.loads(capsys.readouterr().out)
        assert validate_report(out) == []
        assert "compare" in out
        groups = {(r["group"], r["target"]) for r in out["results"]}
        assert ("phases", "startup") in groups
        assert ("phases", "plan") in groups

    def test_compare_two_explicit_files_deterministic(self, tmp_path, capsys):
        factory = _StubKernelFactory()
        bpath = tmp_path / "base.json"
        cpath = tmp_path / "cur.json"
        bpath.write_text(json.dumps(_make_report(_core_results(100.0) + _runtime_results(100.0))))
        cpath.write_text(json.dumps(_make_report(_core_results(100.0) + _runtime_results(100.0))))
        with pytest.raises(SystemExit) as error:
            cmd_benchmark(["compare", str(bpath), str(cpath), "--json"], tmp_path, factory)
        assert error.value.code == 0
        assert factory.calls == 0
        out = json.loads(capsys.readouterr().out)
        assert out["compare"]["live_run"] is False

    def test_compare_single_arg_runs_live(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("AIOS_DEFAULT_MODEL", "ollama")
        monkeypatch.setenv("AIOS_OLLAMA_MODEL", "llama3.2")
        monkeypatch.setenv("AIOS_OLLAMA_HOST", "http://localhost:11434")
        factory = _StubKernelFactory()
        bpath = tmp_path / "base.json"
        baseline = _make_report(
            _core_results(5000.0) + _runtime_results(5000.0),
            system=_system(),
            runtime={"provider": "ollama", "model": "llama3.2", "host": "http://localhost:11434"},
        )
        bpath.write_text(json.dumps(baseline))
        with pytest.raises(SystemExit) as error:
            cmd_benchmark(["compare", str(bpath), "--json"], tmp_path, factory)
        assert error.value.code == 0
        assert factory.calls > 0
        out = json.loads(capsys.readouterr().out)
        assert out["compare"]["live_run"] is True
        assert validate_report(out) == []


class TestCompareCategory:
    def test_compare_category_classification(self):
        for group, target in RUNTIME_DEPENDENT:
            assert category_for(group, target) == "runtime"
        for group, target in [
            ("phases", "startup"),
            ("phases", "kernel_init"),
            ("phases", "context_load"),
            ("phases", "skill_load"),
            ("phases", "telemetry_flush"),
            ("commands", "dashboard"),
            ("commands", "doctor"),
            ("commands", "skills"),
            ("commands", "memory"),
        ]:
            assert category_for(group, target) == "core"
