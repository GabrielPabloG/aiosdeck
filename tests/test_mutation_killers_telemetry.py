"""Mutation-killing tests for telemetry functions.

Targets STRING_MUTATION, ARG_REMOVAL, and CONSTANT_REPLACEMENT survivors in:
- compare.py: compare_reports, category_for, env_divergence, runtime_divergence
- benchmark.py: measure_lifecycle, _extract_observability, percentile, summarize, summarize_runs
- packet.py: GitInfo.detect
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aios.telemetry.benchmark import (
    BARE_PROMPT,
    METRICS,
    PHASES,
    SKIP_REASON,
    _extract_observability,
    error_entry,
    elapsed,
    measure_lifecycle,
    peak_memory_kb,
    percentile,
    sample_start,
    skipped_entry,
    summarize,
    summarize_runs,
)
from aios.telemetry.compare import (
    DEFAULT_THRESHOLD_PCT,
    ENV_KEYS,
    RUNTIME_DEPENDENT,
    RUNTIME_KEYS,
    category_for,
    compare_reports,
    env_divergence,
    runtime_divergence,
)
from aios.telemetry.schema import SCHEMA_VERSION, system_info

_METRICS_ZERO = {"cpu_user_ms": 0.0, "cpu_system_ms": 0.0, "peak_memory_kb": 0.0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report(results, *, system=None, runtime=None, git="abc1234", version="1.0"):
    return {
        "schema_version": SCHEMA_VERSION,
        "aiosdeck_version": version,
        "git_commit": git,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "system_info": system or system_info(),
        "runtime_info": runtime
        or {"provider": "ollama", "model": "llama3.2", "host": "http://localhost:11434"},
        "results": results,
    }


def _result(group, target, samples):
    runs = [{"wall_time_ms": s, **_METRICS_ZERO} for s in samples]
    from aios.telemetry.benchmark import summarize_runs as _sr
    return {"group": group, "target": target, "runs": runs, "summaries": _sr(runs)}


def _find(report, group, target):
    for r in report["results"]:
        if r.get("group") == group and r["target"] == target:
            return r
    raise KeyError((group, target))


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


# ===================================================================
# 1. compare_reports — STRING_MUTATION (verdict, reason, category, exit_code, fields)
# ===================================================================

class TestCompareReportsVerdictStrings:
    """Every verdict/reason/category string must be tested verbatim."""

    def test_no_regression_verdict_ok(self):
        b = _make_report(_core_results(100.0))
        c = _make_report(_core_results(100.0))
        r = compare_reports(b, c)
        for res in r["results"]:
            if not res.get("skipped"):
                assert res["verdict"] == "ok"

    def test_core_regression_verdict_regression(self):
        b = _make_report(_core_results(100.0))
        c = _make_report(_core_results(130.0))
        r = compare_reports(b, c)
        for res in r["results"]:
            if res.get("category") == "core" and not res.get("skipped"):
                assert res["verdict"] == "regression"

    def test_runtime_regression_verdict_warning(self):
        b = _make_report(_runtime_results(100.0))
        c = _make_report(_runtime_results(150.0))
        r = compare_reports(b, c)
        for res in r["results"]:
            if res.get("category") == "runtime" and not res.get("skipped"):
                assert res["verdict"] == "warning"

    def test_skipped_verdict_skipped(self):
        b = _make_report([_result("phases", "startup", [100.0])])
        c = _make_report([])  # no startup in current
        r = compare_reports(b, c)
        skipped = _find(r, "phases", "startup")
        assert skipped["verdict"] == "skipped"
        assert skipped["skipped"] is True

    def test_reason_not_measured_in_current(self):
        """When current has no p50, reason is 'not measured in current'."""
        b = _make_report([_result("phases", "startup", [100.0])])
        c = _make_report([])
        r = compare_reports(b, c)
        s = _find(r, "phases", "startup")
        assert s["reason"] == "not measured in current"

    def test_reason_not_measured_in_baseline(self):
        """When baseline has no p50, reason is 'not measured in baseline'."""
        b = _make_report([])
        c = _make_report([_result("phases", "startup", [100.0])])
        r = compare_reports(b, c)
        s = _find(r, "phases", "startup")
        assert s["reason"] == "not measured in baseline"

    def test_category_runtime_for_plan(self):
        assert category_for("phases", "plan") == "runtime"

    def test_category_runtime_for_agent_exec(self):
        assert category_for("phases", "agent_exec") == "runtime"

    def test_category_core_for_startup(self):
        assert category_for("phases", "startup") == "core"

    def test_category_core_for_kernel_init(self):
        assert category_for("phases", "kernel_init") == "core"

    def test_category_core_for_context_load(self):
        assert category_for("phases", "context_load") == "core"

    def test_category_core_for_skill_load(self):
        assert category_for("phases", "skill_load") == "core"

    def test_category_core_for_telemetry_flush(self):
        assert category_for("phases", "telemetry_flush") == "core"

    def test_category_core_for_commands_plan(self):
        assert category_for("commands", "plan") == "runtime"

    def test_category_core_for_commands_backlog(self):
        assert category_for("commands", "backlog") == "runtime"

    def test_category_core_for_commands_dashboard(self):
        assert category_for("commands", "dashboard") == "core"


class TestCompareReportsExitCode:
    def test_exit_code_zero_no_regression(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert r["compare"]["exit_code"] == 0

    def test_exit_code_one_core_regression(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(130.0)),
        )
        assert r["compare"]["exit_code"] == 1

    def test_exit_code_two_env_divergence(self):
        sys1 = system_info()
        sys2 = {**sys1, "cpu_count": sys1.get("cpu_count", 4) + 100}
        r = compare_reports(
            _make_report(_core_results(100.0), system=sys1),
            _make_report(_core_results(100.0), system=sys2),
        )
        assert r["compare"]["exit_code"] == 2

    def test_exit_code_two_overrides_one(self):
        """Even with core regression, env divergence makes exit_code 2."""
        sys1 = system_info()
        sys2 = {**sys1, "cpu_count": 999}
        r = compare_reports(
            _make_report(_core_results(100.0), system=sys1),
            _make_report(_core_results(200.0), system=sys2),
        )
        assert r["compare"]["exit_code"] == 2


class TestCompareReportsFields:
    def test_compare_key_has_baseline_and_current(self):
        b = _make_report(_core_results(100.0), git="aaa111")
        c = _make_report(_core_results(100.0), git="bbb222")
        r = compare_reports(b, c)
        assert r["compare"]["baseline"]["git_commit"] == "aaa111"
        assert r["compare"]["current"]["git_commit"] == "bbb222"

    def test_compare_has_threshold_pct(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
            threshold=15.0,
        )
        assert r["compare"]["threshold_pct"] == 15.0

    def test_compare_has_live_run_false(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert r["compare"]["live_run"] is False

    def test_compare_has_live_run_true(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
            live=True,
        )
        assert r["compare"]["live_run"] is True

    def test_result_has_baseline_p50_ms(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [123.0])]),
            _make_report([_result("phases", "startup", [123.0])]),
        )
        s = _find(r, "phases", "startup")
        assert s["baseline_p50_ms"] == 123.0

    def test_result_has_current_p50_ms(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [200.0])]),
        )
        s = _find(r, "phases", "startup")
        assert s["current_p50_ms"] == 200.0

    def test_result_has_delta_pct(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [150.0])]),
        )
        s = _find(r, "phases", "startup")
        assert s["delta_pct"] == 50.0

    def test_result_has_category(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [100.0])]),
        )
        s = _find(r, "phases", "startup")
        assert s["category"] == "core"

    def test_result_has_runs(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [100.0])]),
        )
        s = _find(r, "phases", "startup")
        assert "runs" in s
        assert len(s["runs"]) == 1

    def test_result_has_summaries(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [100.0])]),
        )
        s = _find(r, "phases", "startup")
        assert "summaries" in s
        assert "wall_time_ms" in s["summaries"]

    def test_compare_has_env_divergence_list(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert "env_divergence" in r["compare"]
        assert isinstance(r["compare"]["env_divergence"], list)

    def test_compare_has_runtime_divergence_list(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert "runtime_divergence" in r["compare"]
        assert isinstance(r["compare"]["runtime_divergence"], list)

    def test_compare_has_core_regressions_list(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert "core_regressions" in r["compare"]
        assert isinstance(r["compare"]["core_regressions"], list)

    def test_compare_has_runtime_warnings_list(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert "runtime_warnings" in r["compare"]
        assert isinstance(r["compare"]["runtime_warnings"], list)

    def test_compare_has_skipped_list(self):
        r = compare_reports(
            _make_report(_core_results(100.0)),
            _make_report(_core_results(100.0)),
        )
        assert "skipped" in r["compare"]
        assert isinstance(r["compare"]["skipped"], list)

    def test_compare_has_aiosdeck_version_in_baseline_and_current(self):
        b = _make_report(_core_results(100.0), version="1.2.3")
        c = _make_report(_core_results(100.0), version="1.2.4")
        r = compare_reports(b, c)
        assert r["compare"]["baseline"]["aiosdeck_version"] == "1.2.3"
        assert r["compare"]["current"]["aiosdeck_version"] == "1.2.4"


class TestCompareReportsEdgeCases:
    def test_empty_results_both(self):
        r = compare_reports(_make_report([]), _make_report([]))
        assert r["results"] == []
        assert r["compare"]["exit_code"] == 0
        assert r["compare"]["core_regressions"] == []
        assert r["compare"]["skipped"] == []

    def test_single_result(self):
        r = compare_reports(
            _make_report([_result("phases", "startup", [100.0])]),
            _make_report([_result("phases", "startup", [110.0])]),
        )
        assert len(r["results"]) == 1
        assert r["results"][0]["verdict"] == "ok"

    def test_all_skipped(self):
        b = _make_report([_result("phases", "startup", [100.0])])
        c = _make_report([])
        r = compare_reports(b, c)
        all_skipped = all(res.get("skipped") for res in r["results"])
        assert all_skipped

    def test_mixed_categories(self):
        results = _core_results(100.0) + _runtime_results(100.0)
        b = _make_report(results)
        c = _make_report(results)
        r = compare_reports(b, c)
        cats = {res["category"] for res in r["results"] if not res.get("skipped")}
        assert "core" in cats
        assert "runtime" in cats

    def test_threshold_boundary_exactly_at_limit(self):
        """delta_pct exactly at threshold should be ok, not regression."""
        b = _make_report([_result("phases", "startup", [100.0])])
        c = _make_report([_result("phases", "startup", [110.0])])
        r = compare_reports(b, c, threshold=10.0)
        assert _find(r, "phases", "startup")["verdict"] == "ok"

    def test_threshold_boundary_one_above(self):
        b = _make_report([_result("phases", "startup", [100.0])])
        c = _make_report([_result("phases", "startup", [110.1])])
        r = compare_reports(b, c, threshold=10.0)
        assert _find(r, "phases", "startup")["verdict"] == "regression"

    def test_results_envelope_from_current(self):
        b = _make_report(_core_results(100.0), git="old")
        c = _make_report(_core_results(100.0), git="new")
        r = compare_reports(b, c)
        assert r["git_commit"] == "new"


# ===================================================================
# 2. measure_lifecycle — ARG_REMOVAL (project_path, kernel_factory, skip_agents, on_phase, profile, bare_task)
# ===================================================================

class TestMeasureLifecycleArgRemoval:
    """Verify each argument to measure_lifecycle actually affects output."""

    def test_project_path_passed_to_factory(self):
        """kernel_factory must receive the project_path argument."""
        received = []
        kernel = _stub_kernel()

        def factory(path):
            received.append(path)
            return kernel

        measure_lifecycle("/my/project", factory, skip_agents=True)
        assert received == ["/my/project"]

    def test_kernel_factory_called(self):
        """kernel_factory is called to create the kernel."""
        factory = MagicMock(return_value=_stub_kernel())
        measure_lifecycle(".", factory, skip_agents=True)
        factory.assert_called_once_with(".")

    def test_skip_agents_true_produces_skipped(self):
        kernel = _stub_kernel()
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True)
        assert result["plan"] == {"skipped": True, "reason": SKIP_REASON}
        assert result["agent_exec"] == {"skipped": True, "reason": SKIP_REASON}

    def test_skip_agents_false_produces_real_entries(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False)
        assert "wall_time_ms" in result["plan"]
        assert "wall_time_ms" in result["agent_exec"]
        assert result["plan"].get("skipped") is not True

    def test_on_phase_callback_receives_start_and_end(self):
        events = []
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        measure_lifecycle(".", lambda _: kernel, skip_agents=False, on_phase=events.append)
        phase_names = [e[0] for e in events]
        assert "plan" in phase_names
        assert "agent_exec" in phase_names
        assert "telemetry_flush" in phase_names
        # Check start events
        assert ("plan", "start") in events
        assert ("agent_exec", "start") in events
        assert ("telemetry_flush", "start") in events

    def test_on_phase_end_events_have_three_elements(self):
        events = []
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        measure_lifecycle(".", lambda _: kernel, skip_agents=False, on_phase=events.append)
        end_events = [e for e in events if e[1] == "end"]
        for ev in end_events:
            assert len(ev) == 3
            assert isinstance(ev[2], float)

    def test_on_phase_none_still_works(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False, on_phase=None)
        assert "plan" in result

    def test_profile_true_sets_aios_profile_env(self):
        kernel = _stub_kernel()
        kernel.timings = {}
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True, profile=True)
        assert "kernel_init" in result
        # env should be restored
        assert os.environ.get("AIOS_PROFILE") is None

    def test_profile_false_no_aios_profile_env(self):
        kernel = _stub_kernel()
        measure_lifecycle(".", lambda _: kernel, skip_agents=True, profile=False)
        assert os.environ.get("AIOS_PROFILE") is None

    def test_profile_true_adds_timings_when_kernel_has_them(self):
        kernel = _stub_kernel()
        kernel.timings = {"kernel_start_total_ms": 5.0, "engines": {}}
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True, profile=True)
        assert "timings" in result["kernel_init"]
        assert result["kernel_init"]["timings"]["kernel_start_total_ms"] == 5.0

    def test_profile_true_no_timings_when_kernel_has_none(self):
        kernel = _stub_kernel()
        kernel.timings = {}
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True, profile=True)
        assert "timings" not in result["kernel_init"]

    def test_bare_task_uses_restricted_probe(self):
        kernel = _stub_kernel()
        runtime = kernel.get_engine.return_value
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False, bare_task=True)
        assert runtime.execute.called
        prompt, skills, capabilities = runtime.execute.call_args.args
        assert skills == []
        assert capabilities == []
        assert prompt == BARE_PROMPT
        permissions = runtime.execute.call_args.kwargs["permissions"]
        assert permissions.allowed == frozenset()

    def test_bare_task_true_skips_agents_not_called(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        measure_lifecycle(".", lambda _: kernel, skip_agents=False, bare_task=True)
        kernel.run.assert_not_called()
        kernel.run_agent.assert_not_called()

    def test_bare_task_false_runs_agents(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        measure_lifecycle(".", lambda _: kernel, skip_agents=False, bare_task=False)
        kernel.run.assert_called()
        kernel.run_agent.assert_called()

    def test_skip_agents_and_bare_task_both_true_runs_bare(self):
        """When skip_agents=True but bare_task=True, bare_task takes precedence."""
        kernel = _stub_kernel()
        runtime = kernel.get_engine.return_value
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=True, bare_task=True)
        # bare_task=True overrides skip_agents
        assert "wall_time_ms" in result["plan"]
        assert runtime.execute.called

    def test_measure_lifecycle_records_models(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False)
        assert "_models" in result

    def test_measure_lifecycle_seven_phases(self):
        kernel = _stub_kernel()
        kernel.run.return_value = MagicMock(success=True)
        kernel.run_agent.return_value = MagicMock(success=True)
        result = measure_lifecycle(".", lambda _: kernel, skip_agents=False)
        for phase in PHASES:
            assert phase in result

    def test_factory_failure_records_kernel_unavailable(self):
        def bad_factory(path):
            raise RuntimeError("no kernel")

        result = measure_lifecycle(".", bad_factory, skip_agents=True)
        assert result["startup"]["error"] == "no kernel"
        for phase in PHASES[1:]:
            assert result[phase] == error_entry("kernel unavailable")


# ===================================================================
# 3. _extract_observability — STRING_MUTATION (field names, types)
# ===================================================================

class TestExtractObservability:
    def test_all_int_fields(self):
        """int_fields: tool_calls, llm_turns, steps_used, repeated_tool_calls."""
        rr = MagicMock()
        rr.tool_calls = 42
        rr.llm_turns = 7
        rr.steps_used = 15
        rr.repeated_tool_calls = 3
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["tool_calls"] == 42
        assert obs["llm_turns"] == 7
        assert obs["steps_used"] == 15
        assert obs["repeated_tool_calls"] == 3

    def test_all_float_fields(self):
        rr = MagicMock()
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.123
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["total_cost"] == 0.123

    def test_all_str_fields(self):
        rr = MagicMock()
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = "gpt-4o"
        rr.provider = "openai"
        rr.exit_reason = "stop"
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["model"] == "gpt-4o"
        assert obs["provider"] == "openai"
        assert obs["exit_reason"] == "stop"

    def test_bool_fields(self):
        rr = MagicMock()
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.fallback_used = True
        obs = _extract_observability(rr)
        assert obs["fallback_used"] is True

    def test_tool_names_list(self):
        rr = MagicMock()
        rr.tool_names = ["grep", "ls", "cat"]
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["tool_names"] == ["grep", "ls", "cat"]

    def test_tool_durations_ms_list(self):
        rr = MagicMock()
        rr.tool_durations_ms = [1.0, 2.5, 0.3]
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_names = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["tool_durations_ms"] == [1.0, 2.5, 0.3]

    def test_turn_sequence_list(self):
        rr = MagicMock()
        rr.turn_sequence = ["think", "act", "think"]
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.tokens = {}
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["turn_sequence"] == ["think", "act", "think"]

    def test_tokens_dict(self):
        rr = MagicMock()
        rr.tokens = {"input": 500, "output": 200}
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["tokens"] == {"input": 500, "output": 200}

    def test_empty_obs_for_minimal(self):
        rr = MagicMock()
        rr.tool_calls = 0
        rr.llm_turns = 0
        rr.steps_used = 0
        rr.repeated_tool_calls = 0
        rr.total_cost = 0.0
        rr.model = ""
        rr.provider = ""
        rr.exit_reason = ""
        rr.tool_names = ()
        rr.tool_durations_ms = ()
        rr.turn_sequence = ()
        rr.tokens = {}
        rr.fallback_used = False
        obs = _extract_observability(rr)
        assert obs["tool_calls"] == 0
        assert obs["tool_names"] == []
        assert obs["tokens"] == {}


# ===================================================================
# 4. percentile, summarize, summarize_runs — CONSTANT_REPLACEMENT, edge cases
# ===================================================================

class TestPercentileEdgeCases:
    def test_empty_returns_zero(self):
        assert percentile([], 50) == 0.0

    def test_empty_p0(self):
        assert percentile([], 0) == 0.0

    def test_empty_p100(self):
        assert percentile([], 100) == 0.0

    def test_single_value_p0(self):
        assert percentile([5.0], 0) == 5.0

    def test_single_value_p100(self):
        assert percentile([5.0], 100) == 5.0

    def test_two_values_p50(self):
        assert percentile([0.0, 10.0], 50) == 5.0

    def test_two_values_p0(self):
        assert percentile([0.0, 10.0], 0) == 0.0

    def test_two_values_p100(self):
        assert percentile([0.0, 10.0], 100) == 10.0

    def test_four_values_p50(self):
        assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5

    def test_four_values_p75(self):
        assert percentile([1.0, 2.0, 3.0, 4.0], 75) == 3.25

    def test_p95_of_hundred_values(self):
        vals = sorted(range(1, 101))
        p95 = percentile(vals, 95)
        assert 95.0 <= p95 <= 96.0

    def test_p99_of_hundred_values(self):
        vals = sorted(range(1, 101))
        p99 = percentile(vals, 99)
        assert 99.0 <= p99 <= 100.0

    def test_negative_values(self):
        assert percentile([-10.0, 0.0, 10.0], 50) == 0.0

    def test_identical_values(self):
        assert percentile([5.0, 5.0, 5.0], 50) == 5.0
        assert percentile([5.0, 5.0, 5.0], 95) == 5.0


class TestSummarizeEdgeCases:
    def test_empty_all_none(self):
        s = summarize([])
        assert s["count"] == 0
        assert s["min"] is None
        assert s["max"] is None
        assert s["mean"] is None
        assert s["p50"] is None
        assert s["p95"] is None
        assert s["p99"] is None
        assert s["samples"] == []

    def test_single_value_all_fields(self):
        s = summarize([42.0])
        assert s["count"] == 1
        assert s["min"] == 42.0
        assert s["max"] == 42.0
        assert s["mean"] == 42.0
        assert s["p50"] == 42.0
        assert s["p95"] == 42.0
        assert s["p99"] == 42.0
        assert s["samples"] == [42.0]

    def test_two_values(self):
        s = summarize([1.0, 3.0])
        assert s["count"] == 2
        assert s["min"] == 1.0
        assert s["max"] == 3.0
        assert s["mean"] == 2.0
        assert s["p50"] == 2.0

    def test_preserves_raw_order(self):
        raw = [5.0, 1.0, 3.0]
        s = summarize(raw)
        assert s["samples"] == [5.0, 1.0, 3.0]
        assert s["min"] == 1.0
        assert s["max"] == 5.0

    def test_negative_values(self):
        s = summarize([-10.0, 0.0, 10.0])
        assert s["min"] == -10.0
        assert s["max"] == 10.0
        assert s["mean"] == 0.0

    def test_monotonic_percentiles(self):
        s = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
        assert s["p50"] <= s["p95"] <= s["p99"]


class TestSummarizeRuns:
    def test_empty_runs(self):
        result = summarize_runs([])
        assert "wall_time_ms" in result
        assert "cpu_user_ms" in result
        assert "cpu_system_ms" in result
        assert "peak_memory_kb" in result
        for metric in METRICS:
            assert result[metric]["count"] == 0

    def test_single_run(self):
        runs = [{"wall_time_ms": 100.0, "cpu_user_ms": 50.0, "cpu_system_ms": 10.0, "peak_memory_kb": 1024.0}]
        result = summarize_runs(runs)
        assert result["wall_time_ms"]["count"] == 1
        assert result["wall_time_ms"]["p50"] == 100.0
        assert result["cpu_user_ms"]["p50"] == 50.0

    def test_multiple_runs(self):
        runs = [
            {"wall_time_ms": 100.0, "cpu_user_ms": 50.0, "cpu_system_ms": 10.0, "peak_memory_kb": 1024.0},
            {"wall_time_ms": 200.0, "cpu_user_ms": 60.0, "cpu_system_ms": 15.0, "peak_memory_kb": 2048.0},
        ]
        result = summarize_runs(runs)
        assert result["wall_time_ms"]["count"] == 2
        assert result["wall_time_ms"]["min"] == 100.0
        assert result["wall_time_ms"]["max"] == 200.0

    def test_none_metric_skipped(self):
        runs = [{"wall_time_ms": None, "cpu_user_ms": 1.0, "cpu_system_ms": 0.0, "peak_memory_kb": 0.0}]
        result = summarize_runs(runs)
        assert result["wall_time_ms"]["count"] == 0
        assert result["cpu_user_ms"]["count"] == 1


# ===================================================================
# 5. GitInfo.detect — STRING_MUTATION (branch, status, remote, last_commit, last_commit_message)
# ===================================================================

class TestGitInfoDetect:
    def test_no_git_dir_returns_defaults(self):
        from aios.context.packet import GitInfo
        gi = GitInfo.detect(Path("/nonexistent/path"))
        assert gi.branch == ""
        assert gi.status == "unknown"
        assert gi.remote == ""
        assert gi.last_commit == ""
        assert gi.last_commit_message == ""

    def test_no_git_dir_status_is_unknown(self):
        """STRING_MUTATION: 'unknown' must be literal."""
        from aios.context.packet import GitInfo
        gi = GitInfo.detect(Path("/tmp"))
        assert gi.status == "unknown"

    @patch("subprocess.run")
    def test_clean_status(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                m.stdout = "main"
            elif cmd == ["git", "status", "--porcelain"]:
                m.stdout = ""
            elif cmd == ["git", "remote", "get-url", "origin"]:
                m.stdout = "https://github.com/user/repo.git"
            elif cmd == ["git", "rev-parse", "--short", "HEAD"]:
                m.stdout = "abc1234"
            elif cmd == ["git", "log", "-1", "--format=%s"]:
                m.stdout = "feat: add feature"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.branch == "main"
        assert gi.status == "clean"
        assert gi.remote == "https://github.com/user/repo.git"
        assert gi.last_commit == "abc1234"
        assert gi.last_commit_message == "feat: add feature"

    @patch("subprocess.run")
    def test_dirty_status(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                m.stdout = "dev"
            elif cmd == ["git", "status", "--porcelain"]:
                m.stdout = " M file.py"
            elif cmd == ["git", "remote", "get-url", "origin"]:
                m.stdout = ""
            elif cmd == ["git", "rev-parse", "--short", "HEAD"]:
                m.stdout = "deadbeef"
            elif cmd == ["git", "log", "-1", "--format=%s"]:
                m.stdout = "fix: bug"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.branch == "dev"
        assert gi.status == "dirty"
        assert gi.remote == ""
        assert gi.last_commit == "deadbeef"
        assert gi.last_commit_message == "fix: bug"

    @patch("subprocess.run")
    def test_status_clean_string_literal(self, mock_run):
        """STRING_MUTATION: 'clean' must be the exact string."""
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.status == "clean"

    @patch("subprocess.run")
    def test_status_dirty_string_literal(self, mock_run):
        """STRING_MUTATION: 'dirty' must be the exact string."""
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "status", "--porcelain"]:
                m.stdout = " M file.py"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.status == "dirty"

    @patch("subprocess.run")
    def test_branch_from_rev_parse(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
                m.stdout = "feature-branch"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.branch == "feature-branch"

    @patch("subprocess.run")
    def test_remote_from_get_url_origin(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "remote", "get-url", "origin"]:
                m.stdout = "git@github.com:user/repo.git"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.remote == "git@github.com:user/repo.git"

    @patch("subprocess.run")
    def test_last_commit_from_rev_parse_short(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "rev-parse", "--short", "HEAD"]:
                m.stdout = "a1b2c3d"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.last_commit == "a1b2c3d"

    @patch("subprocess.run")
    def test_last_commit_message_from_log_format(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if cmd == ["git", "log", "-1", "--format=%s"]:
                m.stdout = "refactor: cleanup"
            else:
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.last_commit_message == "refactor: cleanup"

    @patch("subprocess.run")
    def test_git_command_failure_returns_empty(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.side_effect = OSError("git not found")
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.branch == ""
        assert gi.remote == ""
        assert gi.last_commit == ""
        assert gi.last_commit_message == ""

    @patch("subprocess.run")
    def test_git_timeout_returns_empty(self, mock_run):
        import subprocess
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        with patch.object(Path, "exists", return_value=True):
            gi = GitInfo.detect(Path("/fake"))
        assert gi.branch == ""

    @patch("subprocess.run")
    def test_git_call_args_correct(self, mock_run):
        """Verify exact git command arguments are used."""
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/proj"))
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["git", "rev-parse", "--abbrev-ref", "HEAD"] in calls
        assert ["git", "status", "--porcelain"] in calls
        assert ["git", "remote", "get-url", "origin"] in calls
        assert ["git", "rev-parse", "--short", "HEAD"] in calls
        assert ["git", "log", "-1", "--format=%s"] in calls

    @patch("subprocess.run")
    def test_git_call_uses_project_path_as_cwd(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/my/project"))
        for call in mock_run.call_args_list:
            assert call.kwargs["cwd"] == Path("/my/project")

    @patch("subprocess.run")
    def test_git_call_timeout_5(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/proj"))
        for call in mock_run.call_args_list:
            assert call.kwargs["timeout"] == 5

    @patch("subprocess.run")
    def test_git_call_check_false(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/proj"))
        for call in mock_run.call_args_list:
            assert call.kwargs["check"] is False

    @patch("subprocess.run")
    def test_git_call_capture_output_true(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/proj"))
        for call in mock_run.call_args_list:
            assert call.kwargs["capture_output"] is True

    @patch("subprocess.run")
    def test_git_call_text_true(self, mock_run):
        from aios.context.packet import GitInfo
        from pathlib import Path

        mock_run.return_value = MagicMock(stdout="")
        with patch.object(Path, "exists", return_value=True):
            GitInfo.detect(Path("/proj"))
        for call in mock_run.call_args_list:
            assert call.kwargs["text"] is True


# ===================================================================
# 6. Helper functions — skipped_entry, error_entry, elapsed
# ===================================================================

class TestHelperFunctions:
    def test_skipped_entry_structure(self):
        e = skipped_entry("test reason")
        assert e == {"skipped": True, "reason": "test reason"}

    def test_skipped_entry_reason_string(self):
        """STRING_MUTATION: reason must be passed through."""
        e = skipped_entry("custom reason here")
        assert e["reason"] == "custom reason here"

    def test_error_entry_structure(self):
        e = error_entry("something broke")
        assert e["wall_time_ms"] == 0.0
        assert e["cpu_user_ms"] == 0.0
        assert e["cpu_system_ms"] == 0.0
        assert e["peak_memory_kb"] == 0.0
        assert e["error"] == "something broke"

    def test_error_entry_zero_constants(self):
        """CONSTANT_REPLACEMENT: zeros must be exactly 0.0."""
        e = error_entry("msg")
        assert e["wall_time_ms"] == 0.0
        assert e["cpu_user_ms"] == 0.0
        assert e["cpu_system_ms"] == 0.0
        assert e["peak_memory_kb"] == 0.0

    def test_error_entry_message_passthrough(self):
        e = error_entry("detailed error message")
        assert e["error"] == "detailed error message"

    def test_peak_memory_kb_non_negative(self):
        val = peak_memory_kb()
        assert isinstance(val, float)
        assert val >= 0.0

    def test_sample_start_returns_three_floats(self):
        wall, user, system = sample_start()
        assert isinstance(wall, float)
        assert isinstance(user, float)
        assert isinstance(system, float)

    def test_elapsed_returns_all_metrics(self):
        wall, user, system = sample_start()
        entry = elapsed(wall, user, system)
        assert "wall_time_ms" in entry
        assert "cpu_user_ms" in entry
        assert "cpu_system_ms" in entry
        assert "peak_memory_kb" in entry
        assert entry["wall_time_ms"] >= 0.0

    def test_elapsed_with_error(self):
        wall, user, system = sample_start()
        entry = elapsed(wall, user, system, error="test error")
        assert entry["error"] == "test error"

    def test_elapsed_without_error(self):
        wall, user, system = sample_start()
        entry = elapsed(wall, user, system)
        assert "error" not in entry


# ===================================================================
# 7. compare module helpers
# ===================================================================

class TestCompareModuleHelpers:
    def test_env_divergence_empty_when_same(self):
        sys_info = system_info()
        r = env_divergence({"system_info": sys_info}, {"system_info": sys_info})
        assert r == []

    def test_env_divergence_detects_cpu_count(self):
        sys1 = system_info()
        sys2 = {**sys1, "cpu_count": 999}
        r = env_divergence({"system_info": sys1}, {"system_info": sys2})
        assert "cpu_count" in r

    def test_env_divergence_detects_python(self):
        sys1 = system_info()
        sys2 = {**sys1, "python": "3.99.0"}
        r = env_divergence({"system_info": sys1}, {"system_info": sys2})
        assert "python" in r

    def test_env_divergence_detects_distro(self):
        sys1 = system_info()
        sys2 = {**sys1, "distro": "FakeOS 1.0"}
        r = env_divergence({"system_info": sys1}, {"system_info": sys2})
        assert "distro" in r

    def test_env_divergence_detects_kernel(self):
        sys1 = system_info()
        sys2 = {**sys1, "kernel": "99.0.0"}
        r = env_divergence({"system_info": sys1}, {"system_info": sys2})
        assert "kernel" in r

    def test_env_divergence_detects_cpu(self):
        sys1 = system_info()
        sys2 = {**sys1, "cpu": "FakeCPU"}
        r = env_divergence({"system_info": sys1}, {"system_info": sys2})
        assert "cpu" in r

    def test_env_divergence_none_system(self):
        r = env_divergence({}, {})
        assert r == []

    def test_runtime_divergence_empty_when_same(self):
        rt = {"provider": "ollama", "model": "llama3", "host": "http://a"}
        r = runtime_divergence({"runtime_info": rt}, {"runtime_info": rt})
        assert r == []

    def test_runtime_divergence_detects_model(self):
        rt1 = {"provider": "ollama", "model": "llama3", "host": "http://a"}
        rt2 = {"provider": "ollama", "model": "gpt4", "host": "http://a"}
        r = runtime_divergence({"runtime_info": rt1}, {"runtime_info": rt2})
        assert "model" in r

    def test_runtime_divergence_detects_provider(self):
        rt1 = {"provider": "ollama", "model": "llama3", "host": "http://a"}
        rt2 = {"provider": "openai", "model": "llama3", "host": "http://a"}
        r = runtime_divergence({"runtime_info": rt1}, {"runtime_info": rt2})
        assert "provider" in r

    def test_runtime_divergence_detects_host(self):
        rt1 = {"provider": "ollama", "model": "llama3", "host": "http://a"}
        rt2 = {"provider": "ollama", "model": "llama3", "host": "http://b"}
        r = runtime_divergence({"runtime_info": rt1}, {"runtime_info": rt2})
        assert "host" in r

    def test_runtime_divergence_none_runtime(self):
        r = runtime_divergence({}, {})
        assert r == []

    def test_default_threshold_pct(self):
        assert DEFAULT_THRESHOLD_PCT == 10.0

    def test_runtime_dependent_set_contains_plan(self):
        assert ("phases", "plan") in RUNTIME_DEPENDENT

    def test_runtime_dependent_set_contains_agent_exec(self):
        assert ("phases", "agent_exec") in RUNTIME_DEPENDENT

    def test_runtime_dependent_set_contains_commands_plan(self):
        assert ("commands", "plan") in RUNTIME_DEPENDENT

    def test_runtime_dependent_set_contains_commands_backlog(self):
        assert ("commands", "backlog") in RUNTIME_DEPENDENT

    def test_env_keys_tuple(self):
        assert ENV_KEYS == ("cpu", "cpu_count", "distro", "kernel", "python")

    def test_runtime_keys_tuple(self):
        assert RUNTIME_KEYS == ("provider", "model", "host")
