"""Data sources for the UI dashboard — overview, health, and usage.

Every function here accepts the :class:`aios.core.kernel.Kernel` and returns
a plain dict ready for rendering. When an engine or its internal store is
``None``, the function returns safe empty defaults so the dashboard never
crashes on a partially-initialized kernel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aios.core.kernel import Kernel
from aios.ui.settings_io import default_config_path, load_ui_section


def overview_data(kernel: Kernel) -> dict[str, Any]:
    """Aggregate top-level dashboard data from the kernel's engines.

    Returns
    -------
    dict
        ``status`` — kernel status (project, engine health, errors).\\
        ``workflow`` — pipeline agent availability (WorkflowHealth).\\
        ``usage_today`` — telemetry totals for the current calendar day.\\
        ``runtime`` — runtime health check and sandbox flag.
    """
    status = kernel.status()

    workflow = workflows_data(kernel)
    usage_today = usage_data(kernel)
    runtime = _runtime_data(kernel)

    return {
        "status": status,
        "workflow": workflow,
        "usage_today": usage_today,
        "runtime": runtime,
    }


def workflows_data(kernel: Kernel) -> dict[str, Any]:
    engine = kernel.get_engine("workflow")
    if engine is None:
        return {"healthy": False, "agents": {}, "optional": []}
    try:
        health = engine.health_check()
    except Exception:  # noqa: BLE001
        return {"healthy": False, "agents": {}, "optional": []}
    return {
        "healthy": health.healthy,
        "agents": dict(health.agents),
        "optional": list(health.optional),
    }


def usage_data(kernel: Kernel) -> dict[str, Any]:
    engine = kernel.get_engine("telemetry")
    if engine is None:
        return {"totals": {}, "by_agent": {}, "by_model": {}, "records": [], "cost_records": []}
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return engine.query(date_from=today, date_to=today)


def agents_data(kernel: Kernel) -> dict[str, Any]:
    engine = kernel.get_engine("telemetry")
    if engine is None:
        return {}
    return engine.query().get("by_agent", {})


def skills_data(kernel: Kernel) -> list[dict[str, Any]]:
    engine = kernel.get_engine("telemetry")
    if engine is None:
        return []
    return engine.query_skill_stats()


def knowledge_data(kernel: Kernel) -> list[dict[str, Any]]:
    engine = kernel.get_engine("telemetry")
    if engine is None:
        return []
    return engine.query_retrieval()


def quality_data(kernel: Kernel) -> list[dict[str, Any]]:
    engine = kernel.get_engine("telemetry")
    if engine is None:
        return []
    return engine.query_gate_stats()


def settings_data(kernel: Kernel) -> dict[str, Any]:
    return load_ui_section(default_config_path())


def _runtime_data(kernel: Kernel) -> dict[str, Any]:
    engine = kernel.get_engine("runtime")
    if engine is None:
        return {"healthy": False, "has_sandbox": False}
    try:
        healthy = engine.health_check()
    except Exception:  # noqa: BLE001
        healthy = False
    try:
        sandbox = engine.has_sandbox
    except Exception:  # noqa: BLE001
        sandbox = False
    return {"healthy": healthy, "has_sandbox": sandbox}
