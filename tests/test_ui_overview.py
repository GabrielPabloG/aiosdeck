"""Tests for the overview data source and page — fake engine classes.

Exercises ``overview_data`` (datasources.py) and ``render_page("overview", …)``
(pages.py) through ``FakeKernel`` with ``FakeWorkflowEngine``,
``FakeTelemetryEngine`` and ``FakeRuntimeEngine``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from aios.ui import (
    ColorMode,
    ColorResolver,
    RenderContext,
    ocean_theme,
    overview_data,
    render_page,
)


# ── Fake engines ──────────────────────────────────────────────────────────────


class FakeWorkflowEngine:
    name = "workflow"

    def __init__(self, agents: dict[str, bool] | None = None, optional: list[str] | None = None) -> None:
        self._agents = agents or {}
        self._optional = optional or []

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def health_check(self) -> "_FakeWorkflowHealth":
        return _FakeWorkflowHealth(
            agents=dict(self._agents),
            optional=list(self._optional),
        )


@dataclass
class _FakeWorkflowHealth:
    agents: dict[str, bool]
    optional: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        required = [n for n in self.agents if n not in self.optional]
        return all(self.agents[n] for n in required)


class FakeTelemetryEngine:
    name = "telemetry"

    def __init__(self, query_result: dict[str, Any] | None = None) -> None:
        self._query_result = query_result or {
            "totals": {},
            "by_agent": {},
            "by_model": {},
            "records": [],
            "cost_records": [],
        }

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def set_event_bus(self, bus: Any) -> None:
        pass

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return self._query_result


class FakeRuntimeEngine:
    name = "runtime"

    def __init__(self, healthy: bool = True, has_sandbox: bool = True) -> None:
        self._healthy = healthy
        self._has_sandbox = has_sandbox

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def health_check(self) -> bool:
        return self._healthy

    @property
    def has_sandbox(self) -> bool:
        return self._has_sandbox


class FakeKernel:
    """Minimal kernel that accepts fake engines and reports status."""

    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()
        self._engines: dict[str, Any] = {}
        self._engine_status: dict[str, str] = {}
        self._errors: list[str] = []

    def register(self, engine: Any) -> None:
        self._engines[engine.name] = engine
        self._engine_status[engine.name] = "ready"

    def get_engine(self, name: str) -> Any:
        return self._engines.get(name)

    def status(self) -> dict[str, Any]:
        return {
            "project": str(self.project_path),
            "engines": dict(self._engine_status),
            "errors": list(self._errors),
        }

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mono_ctx() -> RenderContext:
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    return RenderContext(width=80, height=24, resolver=resolver)


@pytest.fixture
def all_healthy_kernel() -> FakeKernel:
    kernel = FakeKernel()
    kernel.register(
        FakeWorkflowEngine(
            agents={"planner": True, "developer": True, "reviewer": True},
            optional=["tester", "documentation", "git"],
        )
    )
    kernel.register(
        FakeTelemetryEngine(
            query_result={
                "totals": {"requests": 12, "tokens": 3400},
                "by_agent": {"planner": {"requests": 5}},
                "by_model": {},
                "records": [],
                "cost_records": [],
            }
        )
    )
    kernel.register(FakeRuntimeEngine(healthy=True, has_sandbox=True))
    return kernel


# ── overview_data tests ──────────────────────────────────────────────────────


def test_overview_data_all_healthy(all_healthy_kernel: FakeKernel) -> None:
    data = overview_data(all_healthy_kernel)

    assert data["status"]["engines"]["workflow"] == "ready"
    assert data["status"]["engines"]["telemetry"] == "ready"
    assert data["status"]["engines"]["runtime"] == "ready"

    assert data["workflow"]["agents"] == {
        "planner": True,
        "developer": True,
        "reviewer": True,
    }
    assert data["workflow"]["healthy"] is True

    assert data["usage_today"]["totals"] == {"requests": 12, "tokens": 3400}

    assert data["runtime"]["healthy"] is True
    assert data["runtime"]["has_sandbox"] is True


def test_overview_data_missing_agents() -> None:
    kernel = FakeKernel()
    kernel.register(
        FakeWorkflowEngine(
            agents={"planner": True, "developer": False, "reviewer": True},
            optional=["tester"],
        )
    )
    data = overview_data(kernel)

    assert data["workflow"]["agents"]["developer"] is False
    assert data["workflow"]["healthy"] is False
    assert data["workflow"]["optional"] == ["tester"]


def test_overview_data_no_workflow_engine() -> None:
    kernel = FakeKernel()
    kernel.register(FakeTelemetryEngine())
    data = overview_data(kernel)

    assert data["workflow"] == {"healthy": False, "agents": {}, "optional": []}


def test_overview_data_no_telemetry_engine() -> None:
    kernel = FakeKernel()
    kernel.register(FakeRuntimeEngine())
    data = overview_data(kernel)

    assert data["usage_today"] == {
        "totals": {},
        "by_agent": {},
        "by_model": {},
        "records": [],
        "cost_records": [],
    }


def test_overview_data_no_runtime_engine() -> None:
    kernel = FakeKernel()
    data = overview_data(kernel)

    assert data["runtime"] == {"healthy": False, "has_sandbox": False}


def test_overview_data_runtime_unhealthy() -> None:
    kernel = FakeKernel()
    kernel.register(FakeRuntimeEngine(healthy=False, has_sandbox=False))
    data = overview_data(kernel)

    assert data["runtime"]["healthy"] is False
    assert data["runtime"]["has_sandbox"] is False


def test_overview_data_runtime_no_sandbox() -> None:
    kernel = FakeKernel()
    kernel.register(FakeRuntimeEngine(healthy=True, has_sandbox=False))
    data = overview_data(kernel)

    assert data["runtime"]["healthy"] is True
    assert data["runtime"]["has_sandbox"] is False


def test_overview_data_telemetry_empty_store() -> None:
    kernel = FakeKernel()
    kernel.register(FakeTelemetryEngine())
    data = overview_data(kernel)

    assert data["usage_today"]["totals"] == {}
    assert data["usage_today"]["by_agent"] == {}
    assert data["usage_today"]["records"] == []


# ── render_page("overview", …) tests ─────────────────────────────────────────


def test_render_page_shows_system_overview_header(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "System Overview" in output


def test_render_page_shows_project_name(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Project" in output


def test_render_page_shows_engine_count(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Engines" in output


def test_render_page_shows_runtime_ok(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Runtime OK" in output


def test_render_page_shows_sandbox(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Sandbox" in output


def test_render_page_runtime_down_shows_danger(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    kernel.register(FakeRuntimeEngine(healthy=False, has_sandbox=True))
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Runtime Down" in output


def test_render_page_no_sandbox_shows_no_sandbox(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    kernel.register(FakeRuntimeEngine(healthy=True, has_sandbox=False))
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "No Sandbox" in output


def test_render_page_shows_pipeline_section(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Pipeline" in output


def test_render_page_shows_agent_names_and_healthy_marker(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "planner" in output
    assert "developer" in output
    assert "reviewer" in output
    assert "✓" in output


def test_render_page_shows_missing_agent_with_dash(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    kernel.register(
        FakeWorkflowEngine(
            agents={"planner": True, "tester": False},
            optional=["tester"],
        )
    )
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "—" in output


def test_render_page_shows_optional_suffix(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    kernel.register(
        FakeWorkflowEngine(
            agents={"planner": True, "tester": True},
            optional=["tester"],
        )
    )
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "tester" in output
    assert "(opt)" in output


def test_render_page_shows_usage_today_section(all_healthy_kernel: FakeKernel, mono_ctx: RenderContext) -> None:
    data = overview_data(all_healthy_kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Usage Today" in output
    assert "Requests" in output
    assert "12" in output
    assert "Tokens" in output
    assert "3400" in output


def test_render_page_no_usage_hides_usage_today(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    kernel.register(FakeWorkflowEngine(agents={"planner": True}))
    kernel.register(FakeTelemetryEngine())
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Usage Today" not in output


def test_render_page_no_pipeline_when_no_workflow(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "Pipeline" not in output


def test_render_page_no_runtime_when_no_runtime_engine(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    # When no runtime engine is registered, _runtime_data returns
    # {"healthy": False, "has_sandbox": False} which renders as "Runtime Down"
    # and "No Sandbox"
    assert "Runtime Down" in output
    assert "No Sandbox" in output


def test_render_page_empty_all_engines(mono_ctx: RenderContext) -> None:
    kernel = FakeKernel()
    data = overview_data(kernel)
    output = render_page("overview", data, mono_ctx)

    assert "System Overview" in output
    assert "Project" in output
    assert "Engines" in output
    assert "no engines" in output
    assert "Pipeline" not in output
    assert "Usage Today" not in output