"""Tests for ui/pages.py — page-level rendering dispatch and all page renderers.

Targets STRING_MUTATION, ARG_REMOVAL, and CONSTANT_REPLACEMENT survivors
by asserting exact output strings, section headers, and column labels.
"""

import pytest

from aios.ui import ColorMode, ColorResolver, RenderContext, ocean_theme, render_page
from aios.ui.pages import (
    PAGE_NAMES,
    _render_agents,
    _render_knowledge,
    _render_quality,
    _render_skills,
    _render_usage,
    _render_workflows,
)


@pytest.fixture
def ctx() -> RenderContext:
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    return RenderContext(width=120, height=40, resolver=resolver)


class TestRenderPageDispatch:
    def test_all_page_names_are_renderable(self, ctx):
        for name in PAGE_NAMES:
            result = render_page(name, {}, ctx)
            assert isinstance(result, str)

    def test_unknown_page_returns_unknown_message(self, ctx):
        result = render_page("nonexistent_page_xyz", {}, ctx)
        assert "unknown page: nonexistent_page_xyz" in result

    def test_page_names_constant(self):
        assert PAGE_NAMES == [
            "overview",
            "workflows",
            "agents",
            "skills",
            "knowledge",
            "usage",
            "quality",
            "settings",
        ]


class TestRenderOverview:
    def test_overview_with_all_sections(self, ctx):
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
        assert "System Overview" in result
        assert "my-project" in result
        assert "ready" in result
        assert "Pipeline" in result
        assert "planner" in result
        assert "tester" in result
        assert "Usage Today" in result
        assert "Runtime OK" in result
        assert "Sandbox" in result

    def test_overview_runtime_down(self, ctx):
        data = {"status": {"engines": {}, "errors": []}, "runtime": {"healthy": False, "has_sandbox": False}}
        result = render_page("overview", data, ctx)
        assert "Runtime Down" in result
        assert "No Sandbox" in result

    def test_overview_no_engines(self, ctx):
        data = {"status": {"engines": {}, "errors": []}}
        result = render_page("overview", data, ctx)
        assert "no engines" in result

    def test_overview_with_errors(self, ctx):
        data = {"status": {"engines": {"t": "ready"}, "errors": ["something broke"]}}
        result = render_page("overview", data, ctx)
        assert "System Overview" in result
        assert "Project" in result


class TestRenderWorkflows:
    def test_healthy_workflow(self, ctx):
        data = {"healthy": True, "agents": {"planner": True, "developer": True}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "Workflows" in result
        assert "Healthy" in result
        assert "planner" in result

    def test_unhealthy_workflow(self, ctx):
        data = {"healthy": False, "agents": {"planner": False}, "optional": []}
        result = _render_workflows(data, ctx)
        assert "Unhealthy" in result


class TestRenderAgents:
    def test_agents_with_data(self, ctx):
        data = {"planner": 10, "developer": 5}
        result = _render_agents(data, ctx)
        assert "Agents" in result
        assert "planner" in result
        assert "10" in result

    def test_agents_empty(self, ctx):
        result = _render_agents({}, ctx)
        assert "no data" in result


class TestRenderSkills:
    def test_skills_with_data(self, ctx):
        data = [{"name": "test-skill", "invocations": 3, "avg_duration_ms": 120.5}]
        result = _render_skills(data, ctx)
        assert "Skills" in result
        assert "test-skill" in result
        assert "Invocations" in result
        assert "Avg Duration" in result

    def test_skills_empty(self, ctx):
        result = _render_skills([], ctx)
        assert "no data" in result


class TestRenderKnowledge:
    def test_knowledge_with_data(self, ctx):
        data = [{"source": "docs", "retrievals": 7, "confidence": 0.95}]
        result = _render_knowledge(data, ctx)
        assert "Knowledge" in result
        assert "docs" in result
        assert "Retrievals" in result
        assert "Confidence" in result

    def test_knowledge_empty(self, ctx):
        result = _render_knowledge([], ctx)
        assert "no data" in result


class TestRenderUsage:
    def test_usage_all_sections(self, ctx):
        data = {
            "totals": {"input_tokens": 500, "output_tokens": 200},
            "by_agent": {"planner": 30, "developer": 20},
            "by_model": {"gpt-4o": 50},
            "cost_records": [{"agent": "planner", "model": "gpt-4o", "cost": 0.0123}],
        }
        result = _render_usage(data, ctx)
        assert "Usage" in result
        assert "input_tokens" in result or "Input_tokens" in result
        assert "Per Agent" in result
        assert "planner" in result
        assert "Per Model" in result
        assert "gpt-4o" in result
        assert "Costs" in result
        assert "$" in result

    def test_usage_empty(self, ctx):
        result = _render_usage({}, ctx)
        assert "Usage" in result


class TestRenderQuality:
    def test_quality_with_data(self, ctx):
        data = [{"gate": "lint", "status": "passed", "duration_ms": 150}]
        result = _render_quality(data, ctx)
        assert "Quality Gates" in result
        assert "lint" in result
        assert "passed" in result

    def test_quality_empty(self, ctx):
        result = _render_quality([], ctx)
        assert "no data" in result
