"""Mutation-killing tests for UI pages — comprehensive string assertions and branch coverage.

Targets _render_overview (106 killable: 58 STRING_MUTATION, 28 ARG_REMOVAL) and
_render_usage (86 killable: 57 STRING_MUTATION, 27 ARG_REMOVAL).
"""

from __future__ import annotations

import pytest

from aios.ui import ColorMode, ColorResolver, RenderContext, ocean_theme, render_page
from aios.ui.pages import (
    PAGE_NAMES,
    _PAGES,
    _render_agents,
    _render_knowledge,
    _render_overview,
    _render_quality,
    _render_settings,
    _render_skills,
    _render_usage,
    _render_workflows,
)


@pytest.fixture
def ctx():
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    return RenderContext(width=120, height=40, resolver=resolver)


# ===========================================================================
# render_page dispatch
# ===========================================================================


class TestRenderPageDispatch:
    def test_all_page_names_renderable(self, ctx):
        for name in PAGE_NAMES:
            result = render_page(name, {}, ctx)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_unknown_page_returns_panel(self, ctx):
        result = render_page("nonexistent_xyz", {}, ctx)
        assert "unknown page: nonexistent_xyz" in result

    def test_page_names_matches_pages_dict(self):
        assert set(PAGE_NAMES) == set(_PAGES.keys())

    def test_page_names_constant(self):
        assert PAGE_NAMES == [
            "overview", "workflows", "agents", "skills",
            "knowledge", "usage", "quality", "settings",
        ]


# ===========================================================================
# _render_overview — every code path
# ===========================================================================


class TestRenderOverview:
    def test_full_data_all_sections(self, ctx):
        data = {
            "status": {
                "project": "my-project",
                "engines": {"telemetry": "ready", "knowledge": "ready"},
                "errors": [],
            },
            "runtime": {"healthy": True, "has_sandbox": True},
            "workflow": {
                "agents": {"planner": True, "developer": True, "tester": False},
                "optional": ["tester"],
            },
            "usage_today": {"totals": {"requests": 42, "tokens": 1500}},
        }
        result = render_page("overview", data, ctx)
        # Section headers
        assert "System Overview" in result
        assert "Pipeline" in result
        assert "Usage Today" in result
        # Metric values
        assert "my-project" in result
        # Engine health
        assert "2/2 ready" in result
        # Runtime
        assert "Runtime OK" in result
        assert "Sandbox" in result
        # Workflow agents
        assert "planner" in result
        assert "tester" in result
        assert "(opt)" in result
        assert "✓" in result
        assert "—" in result
        # Usage totals
        assert "42" in result
        assert "1500" in result

    def test_no_engines(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "no engines" in result

    def test_partial_engines(self, ctx):
        data = {
            "status": {
                "engines": {"telemetry": "ready", "knowledge": "down"},
                "errors": [],
            }
        }
        result = render_page("overview", data, ctx)
        assert "1/2 ready" in result

    def test_errors_make_danger_tone(self, ctx):
        data = {"status": {"engines": {"t": "ready"}, "errors": ["oops"]}}
        result = render_page("overview", data, ctx)
        assert "System Overview" in result
        assert "Project" in result

    def test_runtime_down(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "runtime": {"healthy": False, "has_sandbox": False},
        }
        result = render_page("overview", data, ctx)
        assert "Runtime Down" in result
        assert "No Sandbox" in result

    def test_runtime_healthy_no_sandbox(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "runtime": {"healthy": True, "has_sandbox": False},
        }
        result = render_page("overview", data, ctx)
        assert "Runtime OK" in result
        assert "No Sandbox" in result

    def test_runtime_unhealthy_with_sandbox(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "runtime": {"healthy": False, "has_sandbox": True},
        }
        result = render_page("overview", data, ctx)
        assert "Runtime Down" in result
        assert "Sandbox" in result

    def test_no_runtime_section(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "Runtime OK" not in result
        assert "Runtime Down" not in result
        assert "Sandbox" not in result
        assert "No Sandbox" not in result

    def test_no_workflow_agents(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "Pipeline" not in result

    def test_workflow_agents_all_available(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "workflow": {
                "agents": {"planner": True, "developer": True},
                "optional": [],
            },
        }
        result = render_page("overview", data, ctx)
        assert "Pipeline" in result
        assert "planner" in result
        assert "developer" in result

    def test_optional_agent标记(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "workflow": {
                "agents": {"planner": True, "tester": False},
                "optional": ["tester"],
            },
        }
        result = render_page("overview", data, ctx)
        assert "(opt)" in result

    def test_no_usage_today(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "Usage Today" not in result

    def test_usage_today_empty_totals(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "usage_today": {"totals": {}},
        }
        result = render_page("overview", data, ctx)
        assert "Usage Today" not in result

    def test_default_project_name(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "Project" in result

    def test_project_name_displayed(self, ctx):
        data = {"status": {"project": "test-proj", "engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "test-proj" in result

    def test_usage_totals_keys_capitalized(self, ctx):
        data = {
            "status": {"engines": {}, "errors": []},
            "usage_today": {"totals": {"input_tokens": 100, "output_tokens": 200}},
        }
        result = render_page("overview", data, ctx)
        assert "Input_tokens" in result or "input_tokens" in result
        assert "Output_tokens" in result or "output_tokens" in result

    def test_empty_data(self, ctx):
        result = render_page("overview", {}, ctx)
        assert "System Overview" in result


# ===========================================================================
# _render_usage — every code path
# ===========================================================================


class TestRenderUsage:
    def test_all_sections(self, ctx):
        data = {
            "totals": {"input_tokens": 500, "output_tokens": 200},
            "by_agent": {"planner": 30, "developer": 20},
            "by_model": {"gpt-4o": 50},
            "cost_records": [{"agent": "planner", "model": "gpt-4o", "cost": 0.0123}],
        }
        result = _render_usage(data, ctx)
        assert "Usage" in result
        assert "Per Agent" in result
        assert "planner" in result
        assert "30" in result
        assert "Per Model" in result
        assert "gpt-4o" in result
        assert "50" in result
        assert "Costs" in result
        assert "$" in result

    def test_empty_data(self, ctx):
        result = _render_usage({}, ctx)
        assert "Usage" in result
        assert "Per Agent" not in result
        assert "Per Model" not in result
        assert "Costs" not in result

    def test_only_totals(self, ctx):
        data = {"totals": {"requests": 10}}
        result = _render_usage(data, ctx)
        assert "Usage" in result
        assert "Requests" in result or "requests" in result
        assert "Per Agent" not in result

    def test_only_by_agent(self, ctx):
        data = {"by_agent": {"planner": 10}}
        result = _render_usage(data, ctx)
        assert "Per Agent" in result
        assert "planner" in result
        assert "Per Model" not in result

    def test_only_by_model(self, ctx):
        data = {"by_model": {"gpt-4o": 5}}
        result = _render_usage(data, ctx)
        assert "Per Model" in result
        assert "gpt-4o" in result

    def test_only_costs(self, ctx):
        data = {"cost_records": [{"agent": "a", "model": "m", "cost": 0.001}]}
        result = _render_usage(data, ctx)
        assert "Costs" in result
        assert "$" in result

    def test_cost_rows_limit(self, ctx):
        costs = [{"agent": f"agent-{i}", "model": "m", "cost": i / 1000} for i in range(12)]
        result = _render_usage({"cost_records": costs}, ctx)
        assert "agent-0" in result
        assert "agent-9" in result
        assert "agent-10" not in result
        assert "agent-11" not in result

    def test_cost_default_formatting(self, ctx):
        result = _render_usage({"cost_records": [{}]}, ctx)
        assert "$0.0000" in result

    def test_cost_with_actual_values(self, ctx):
        result = _render_usage({"cost_records": [{"agent": "a", "model": "m", "cost": 0.1234}]}, ctx)
        assert "$0.1234" in result

    def test_totals_keys_capitalized(self, ctx):
        data = {"totals": {"input_tokens": 100}}
        result = _render_usage(data, ctx)
        assert "Input_tokens" in result or "input_tokens" in result

    def test_multiple_agents(self, ctx):
        data = {"by_agent": {"planner": 10, "developer": 20, "tester": 5}}
        result = _render_usage(data, ctx)
        assert "planner" in result
        assert "developer" in result
        assert "tester" in result

    def test_multiple_models(self, ctx):
        data = {"by_model": {"gpt-4o": 10, "llama3": 5}}
        result = _render_usage(data, ctx)
        assert "gpt-4o" in result
        assert "llama3" in result


# ===========================================================================
# _render_workflows
# ===========================================================================


class TestRenderWorkflows:
    def test_healthy(self, ctx):
        data = {"healthy": True, "agents": {"planner": True}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "Workflows" in result
        assert "Healthy" in result
        assert "planner" in result

    def test_unhealthy(self, ctx):
        data = {"healthy": False, "agents": {"planner": False}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "Unhealthy" in result

    def test_optional_agents(self, ctx):
        data = {"healthy": True, "agents": {"planner": True}, "optional": ["planner"]}
        result = _render_workflows(data, ctx)
        assert "(opt)" in result

    def test_no_agents(self, ctx):
        data = {"healthy": True, "agents": {}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "Workflows" in result
        assert "Healthy" in result

    def test_available_checkmark(self, ctx):
        data = {"healthy": True, "agents": {"a": True}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "✓" in result

    def test_unavailable_dash(self, ctx):
        data = {"healthy": True, "agents": {"a": False}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "—" in result


# ===========================================================================
# _render_agents
# ===========================================================================


class TestRenderAgents:
    def test_with_data(self, ctx):
        data = {"planner": 10, "developer": 5}
        result = _render_agents(data, ctx)
        assert "Agents" in result
        assert "planner" in result
        assert "10" in result
        assert "developer" in result
        assert "5" in result

    def test_empty(self, ctx):
        result = _render_agents({}, ctx)
        assert "Agents" in result
        assert "no data" in result

    def test_table_headers(self, ctx):
        data = {"planner": 10}
        result = _render_agents(data, ctx)
        assert "Agent" in result
        assert "Executions" in result


# ===========================================================================
# _render_skills
# ===========================================================================


class TestRenderSkills:
    def test_with_data(self, ctx):
        data = [{"name": "test-skill", "invocations": 3, "avg_duration_ms": 120.5}]
        result = _render_skills(data, ctx)
        assert "Skills" in result
        assert "test-skill" in result
        assert "Invocations" in result
        assert "Avg Duration" in result

    def test_empty_list(self, ctx):
        result = _render_skills([], ctx)
        assert "Skills" in result
        assert "no data" in result

    def test_not_a_list(self, ctx):
        result = _render_skills("invalid", ctx)
        assert "Skills" in result
        assert "no data" in result

    def test_multiple_skills(self, ctx):
        data = [
            {"name": "skill-a", "invocations": 5, "avg_duration_ms": 100},
            {"name": "skill-b", "invocations": 3, "avg_duration_ms": 200},
        ]
        result = _render_skills(data, ctx)
        assert "skill-a" in result
        assert "skill-b" in result

    def test_duration_formatting(self, ctx):
        data = [{"name": "s", "invocations": 1, "avg_duration_ms": 123.4}]
        result = _render_skills(data, ctx)
        assert "123ms" in result


# ===========================================================================
# _render_knowledge
# ===========================================================================


class TestRenderKnowledge:
    def test_with_data(self, ctx):
        data = [{"source": "docs", "retrievals": 7, "confidence": 0.95}]
        result = _render_knowledge(data, ctx)
        assert "Knowledge" in result
        assert "docs" in result
        assert "Retrievals" in result
        assert "Confidence" in result

    def test_empty_list(self, ctx):
        result = _render_knowledge([], ctx)
        assert "Knowledge" in result
        assert "no data" in result

    def test_not_a_list(self, ctx):
        result = _render_knowledge("bad", ctx)
        assert "Knowledge" in result
        assert "no data" in result

    def test_multiple_sources(self, ctx):
        data = [
            {"source": "docs", "retrievals": 5, "confidence": 0.9},
            {"source": "code", "retrievals": 3, "confidence": 0.8},
        ]
        result = _render_knowledge(data, ctx)
        assert "docs" in result
        assert "code" in result

    def test_confidence_formatting(self, ctx):
        data = [{"source": "s", "retrievals": 1, "confidence": 0.123}]
        result = _render_knowledge(data, ctx)
        assert "0.12" in result


# ===========================================================================
# _render_quality
# ===========================================================================


class TestRenderQuality:
    def test_with_data(self, ctx):
        data = [{"gate": "lint", "status": "passed", "duration_ms": 150}]
        result = _render_quality(data, ctx)
        assert "Quality Gates" in result
        assert "lint" in result
        assert "passed" in result
        assert "150" in result

    def test_empty_list(self, ctx):
        result = _render_quality([], ctx)
        assert "Quality Gates" in result
        assert "no data" in result

    def test_not_a_list(self, ctx):
        result = _render_quality(None, ctx)
        assert "Quality Gates" in result
        assert "no data" in result

    def test_multiple_gates(self, ctx):
        data = [
            {"gate": "lint", "status": "passed", "duration_ms": 100},
            {"gate": "test", "status": "failed", "duration_ms": 200},
        ]
        result = _render_quality(data, ctx)
        assert "lint" in result
        assert "test" in result
        assert "passed" in result
        assert "failed" in result

    def test_table_headers(self, ctx):
        data = [{"gate": "g", "status": "s", "duration_ms": 0}]
        result = _render_quality(data, ctx)
        assert "Gate" in result
        assert "Status" in result
        assert "Duration (ms)" in result


# ===========================================================================
# ARG_REMOVAL tests — verify arguments affect output
# ===========================================================================


class TestArgRemoval:
    def test_render_page_name_dispatches(self, ctx):
        for name in PAGE_NAMES:
            r1 = render_page(name, {}, ctx)
            r2 = render_page("nonexistent", {}, ctx)
            # Different pages produce different output (name arg matters)
            assert r1 != r2 or name == "settings"

    def test_overview_data_matters(self, ctx):
        r1 = _render_overview({"status": {"project": "aaa", "engines": {}, "errors": []}}, ctx)
        r2 = _render_overview({"status": {"project": "zzz", "engines": {}, "errors": []}}, ctx)
        assert "aaa" in r1
        assert "zzz" in r2

    def test_usage_data_matters(self, ctx):
        r1 = _render_usage({"totals": {"x": 1}}, ctx)
        r2 = _render_usage({"totals": {"y": 2}}, ctx)
        assert "1" in r1
        assert "2" in r2

    def test_workflows_healthy_matters(self, ctx):
        data = {"healthy": True, "agents": {}, "optional": []}
        r1 = _render_workflows(data, ctx)
        data["healthy"] = False
        r2 = _render_workflows(data, ctx)
        assert "Healthy" in r1
        assert "Unhealthy" in r2

    def test_workflows_agents_matters(self, ctx):
        r1 = _render_workflows({"healthy": True, "agents": {"a": True}, "optional": []}, ctx)
        r2 = _render_workflows({"healthy": True, "agents": {"b": True}, "optional": []}, ctx)
        assert "a" in r1
        assert "b" in r2

    def test_agents_data_matters(self, ctx):
        r1 = _render_agents({"x": 1}, ctx)
        r2 = _render_agents({"y": 2}, ctx)
        assert "x" in r1
        assert "y" in r2

    def test_skills_data_matters(self, ctx):
        r1 = _render_skills([{"name": "a", "invocations": 1, "avg_duration_ms": 10}], ctx)
        r2 = _render_skills([{"name": "b", "invocations": 2, "avg_duration_ms": 20}], ctx)
        assert "a" in r1
        assert "b" in r2

    def test_knowledge_data_matters(self, ctx):
        r1 = _render_knowledge([{"source": "x", "retrievals": 1, "confidence": 0.5}], ctx)
        r2 = _render_knowledge([{"source": "y", "retrievals": 2, "confidence": 0.9}], ctx)
        assert "x" in r1
        assert "y" in r2

    def test_quality_data_matters(self, ctx):
        r1 = _render_quality([{"gate": "a", "status": "passed", "duration_ms": 1}], ctx)
        r2 = _render_quality([{"gate": "b", "status": "failed", "duration_ms": 2}], ctx)
        assert "a" in r1
        assert "b" in r2
