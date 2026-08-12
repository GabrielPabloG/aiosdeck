"""Regression tests for the ``aios`` dashboard page data mapping.

The dashboard (``cmd_dashboard``) and ``aios ocean`` must feed each page its
own data source. A previous bug routed ``overview_data`` to every page, which
made the workflows page report ``Unhealthy`` and the agents page render the
overview keys as rows.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aios.cli.commands.core import cmd_dashboard
from aios.ui.datasources import PAGE_DATA


class FakeKernel:
    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()

    def start(self, render_dashboard: bool = True) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {
            "project": str(self.project_path),
            "engines": {"config": "ready", "workflow": "ready"},
            "errors": [],
        }

    def get_engine(self, name: str) -> Any:
        if name == "workflow":
            health = SimpleNamespace(
                healthy=True,
                agents={"planner": True, "reviewer": True},
                optional=["reviewer"],
            )
            return SimpleNamespace(health_check=lambda: health)
        if name == "runtime":
            return SimpleNamespace(health_check=lambda: True, has_sandbox=True)
        if name == "telemetry":
            return SimpleNamespace(
                query=lambda date_from=None, date_to=None: {
                    "totals": {"total_tokens": 0},
                    "by_agent": {"planner": 3},
                    "by_model": {},
                    "records": [],
                    "cost_records": [],
                },
                query_skill_stats=lambda: [],
                query_retrieval=lambda: [],
                query_gate_stats=lambda: [],
            )
        return None


def _run_dashboard(monkeypatch) -> dict[str, str]:
    """Invoke ``cmd_dashboard`` capturing the render closure per page."""
    rendered: dict[str, str] = {}

    def _fake_run_tui(render: Any, page_names: list[str], **_: Any) -> None:
        for name in page_names:
            rendered[name] = render(name)

    monkeypatch.setattr("aios.ui.run_tui", _fake_run_tui)
    cmd_dashboard([], Path.cwd(), lambda _: FakeKernel())
    return rendered


def test_page_data_covers_all_pages() -> None:
    from aios.ui import PAGE_NAMES

    assert set(PAGE_DATA) == set(PAGE_NAMES)


def test_page_data_feeds_each_page_its_own_source() -> None:
    kernel = FakeKernel()
    assert PAGE_DATA["workflows"](kernel)["healthy"] is True
    assert PAGE_DATA["agents"](kernel) == {"planner": 3}


def test_dashboard_workflows_page_shows_healthy(monkeypatch) -> None:
    rendered = _run_dashboard(monkeypatch)
    out = rendered["workflows"]
    assert "Healthy" in out
    assert "Unhealthy" not in out
    assert "planner" in out


def test_dashboard_agents_page_shows_agent_executions(monkeypatch) -> None:
    rendered = _run_dashboard(monkeypatch)
    out = rendered["agents"]
    assert "planner" in out
    assert "status" not in out
    assert "usage_today" not in out
    assert "runtime" not in out


def test_dashboard_overview_page_still_works(monkeypatch) -> None:
    rendered = _run_dashboard(monkeypatch)
    out = rendered["overview"]
    assert "2/2 ready" in out
    assert "Runtime OK" in out
