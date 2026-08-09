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
)


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
    health_label = (
        f"{ready_count}/{len(engines)} ready"
        if engines
        else "no engines"
    )
    metrics.append(render_metric_card(ctx, "Engines", health_label, tone=health_tone))

    if runtime:
        runtime_tone = "success" if runtime.get("healthy") else "danger"
        runtime_label = "Runtime OK" if runtime.get("healthy") else "Runtime Down"
        metrics.append(
            render_status_pill(ctx, runtime_label, tone=runtime_tone)
        )
        sandbox_tone = "info" if runtime.get("has_sandbox") else "warning"
        sandbox_label = "Sandbox" if runtime.get("has_sandbox") else "No Sandbox"
        metrics.append(
            render_status_pill(ctx, sandbox_label, tone=sandbox_tone)
        )

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


_PAGES: dict[str, Any] = {
    "overview": _render_overview,
}