"""Page-level rendering — dispatch on page name to compose dashboard layouts.

Each ``render_page`` call produces a complete ``str`` from structured data and
a shared ``RenderContext``. Pages compose the primitive widgets from
:mod:`aios.ui.components` and never call the resolver directly.
"""

from __future__ import annotations

from typing import Any

from aios.ui.components import (
    RenderContext,
    render_metric_card,
    render_panel,
    render_section_header,
    render_status_pill,
    render_table,
)
from aios.ui.settings_page import render_settings_page


def render_page(name: str, data: dict[str, Any], ctx: RenderContext) -> str:
    """Dispatch to a named page builder and return its text output.

    Parameters
    ----------
    name:
        Page identifier (e.g. ``"overview"``).
    data:
        Structured data for the page, keyed by section.
    ctx:
        Shared rendering context for all widgets on the page.

    Returns
    -------
    str
        Fully rendered page output (multi-line, no trailing newline).
    """
    builder = _PAGES.get(name)
    if builder is None:
        return render_panel(ctx, title=f"unknown page: {name}", body="", border="default")
    return builder(data, ctx)


def _render_overview(data: dict[str, Any], ctx: RenderContext) -> str:
    lines: list[str] = []

    status: dict = data.get("status", {})
    workflow: dict = data.get("workflow", {})
    usage: dict = data.get("usage_today", {})
    runtime: dict = data.get("runtime", {})

    sections = []

    sections.append(render_section_header(ctx, "System Overview", tone="info"))

    name = status.get("project", ".")
    metrics = [
        render_metric_card(ctx, "Project", name, tone="info"),
    ]

    engines: dict = status.get("engines", {})
    ready_count = sum(1 for s in engines.values() if s == "ready")
    errors = status.get("errors", [])
    health_tone = "danger" if errors else "success" if ready_count == len(engines) else "warning"
    health_label = f"{ready_count}/{len(engines)} ready" if engines else "no engines"
    metrics.append(render_metric_card(ctx, "Engines", health_label, tone=health_tone))

    if runtime:
        runtime_tone = "success" if runtime.get("healthy") else "danger"
        runtime_label = "Runtime OK" if runtime.get("healthy") else "Runtime Down"
        metrics.append(render_status_pill(ctx, runtime_label, tone=runtime_tone))
        sandbox_tone = "info" if runtime.get("has_sandbox") else "warning"
        sandbox_label = "Sandbox" if runtime.get("has_sandbox") else "No Sandbox"
        metrics.append(render_status_pill(ctx, sandbox_label, tone=sandbox_tone))

    sections.extend(metrics)

    workflow_agents: dict = workflow.get("agents", {})
    if workflow_agents:
        sections.append(render_section_header(ctx, "Pipeline", tone="info"))
        optional = set(workflow.get("optional", []))
        for name, available in workflow_agents.items():
            tag = " (opt)" if name in optional else ""
            tone = "success" if available else "danger"
            sections.append(
                render_metric_card(ctx, f"{name}{tag}", "✓" if available else "—", tone=tone)
            )

    totals: dict = usage.get("totals", {})
    if totals:
        sections.append(render_section_header(ctx, "Usage Today", tone="info"))
        for key, value in totals.items():
            sections.append(render_metric_card(ctx, key.capitalize(), str(value), tone="success"))

    lines = [s for s in sections if s]
    return "\n".join(lines)


def _render_workflows(data: dict[str, Any], ctx: RenderContext) -> str:
    lines: list[str] = []
    sections = []

    sections.append(render_section_header(ctx, "Workflows", tone="info"))

    healthy = data.get("healthy", False)
    sections.append(
        render_status_pill(
            ctx,
            "Healthy" if healthy else "Unhealthy",
            tone="success" if healthy else "danger",
        )
    )

    agents: dict = data.get("agents", {})
    optional: list = data.get("optional", [])
    if agents:
        rows = [
            [name, "✓" if avail else "—", "(opt)" if name in optional else ""]
            for name, avail in agents.items()
        ]
        sections.append(render_table(ctx, ["Agent", "Available", ""], rows, tone="info"))

    lines = [s for s in sections if s]
    return "\n".join(lines)


def _render_agents(data: dict[str, Any], ctx: RenderContext) -> str:
    sections = []
    sections.append(render_section_header(ctx, "Agents", tone="info"))

    if not data:
        sections.append(render_metric_card(ctx, "Agents", "no data", tone="warning"))
    else:
        rows = [[agent, str(count)] for agent, count in data.items()]
        sections.append(render_table(ctx, ["Agent", "Executions"], rows, tone="info"))

    return "\n".join(s for s in sections if s)


def _render_skills(data: dict[str, Any], ctx: RenderContext) -> str:
    sections = []
    sections.append(render_section_header(ctx, "Skills", tone="info"))

    if isinstance(data, list) and data:
        rows = [
            [
                s.get("name", ""),
                str(s.get("invocations", 0)),
                f"{s.get('avg_duration_ms', 0):.0f}ms",
            ]
            for s in data
        ]
        sections.append(
            render_table(ctx, ["Skill", "Invocations", "Avg Duration"], rows, tone="info")
        )
    else:
        sections.append(render_metric_card(ctx, "Skills", "no data", tone="warning"))

    return "\n".join(s for s in sections if s)


def _render_knowledge(data: dict[str, Any], ctx: RenderContext) -> str:
    sections = []
    sections.append(render_section_header(ctx, "Knowledge", tone="info"))

    if isinstance(data, list) and data:
        rows = [
            [s.get("source", ""), str(s.get("retrievals", 0)), f"{s.get('confidence', 0):.2f}"]
            for s in data
        ]
        sections.append(
            render_table(ctx, ["Source", "Retrievals", "Confidence"], rows, tone="info")
        )
    else:
        sections.append(render_metric_card(ctx, "Knowledge", "no data", tone="warning"))

    return "\n".join(s for s in sections if s)


def _render_usage(data: dict[str, Any], ctx: RenderContext) -> str:
    sections = []
    sections.append(render_section_header(ctx, "Usage", tone="info"))

    totals: dict = data.get("totals", {})
    if totals:
        for key, value in totals.items():
            sections.append(render_metric_card(ctx, key.capitalize(), str(value), tone="success"))

    by_agent: dict = data.get("by_agent", {})
    if by_agent:
        sections.append(render_section_header(ctx, "Per Agent", tone="info"))
        rows = [[agent, str(count)] for agent, count in by_agent.items()]
        sections.append(render_table(ctx, ["Agent", "Calls"], rows, tone="info"))

    by_model: dict = data.get("by_model", {})
    if by_model:
        sections.append(render_section_header(ctx, "Per Model", tone="info"))
        rows = [[model, str(count)] for model, count in by_model.items()]
        sections.append(render_table(ctx, ["Model", "Calls"], rows, tone="info"))

    costs: list = data.get("cost_records", [])
    if costs:
        sections.append(render_section_header(ctx, "Costs", tone="info"))
        rows = [
            [c.get("agent", ""), c.get("model", ""), f"${c.get('cost', 0):.4f}"] for c in costs[:10]
        ]
        sections.append(render_table(ctx, ["Agent", "Model", "Cost"], rows, tone="info"))

    return "\n".join(s for s in sections if s)


def _render_quality(data: dict[str, Any], ctx: RenderContext) -> str:
    sections = []
    sections.append(render_section_header(ctx, "Quality Gates", tone="info"))

    if isinstance(data, list) and data:
        rows = [
            [g.get("gate", ""), g.get("status", ""), str(g.get("duration_ms", 0))] for g in data
        ]
        sections.append(render_table(ctx, ["Gate", "Status", "Duration (ms)"], rows, tone="info"))
    else:
        sections.append(render_metric_card(ctx, "Quality", "no data", tone="warning"))

    return "\n".join(s for s in sections if s)


def _render_settings(data: dict[str, Any], ctx: RenderContext) -> str:
    return render_settings_page(data, ctx)


PAGE_NAMES = [
    "overview",
    "workflows",
    "agents",
    "skills",
    "knowledge",
    "usage",
    "quality",
    "settings",
]

_PAGES: dict[str, Any] = {
    "overview": _render_overview,
    "workflows": _render_workflows,
    "agents": _render_agents,
    "skills": _render_skills,
    "knowledge": _render_knowledge,
    "usage": _render_usage,
    "quality": _render_quality,
    "settings": _render_settings,
}
