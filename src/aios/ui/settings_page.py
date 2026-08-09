"""Settings page renderer — surface the current UI configuration.

Reads the ``ui`` section (as produced by :func:`aios.ui.settings_io.load_ui_section`)
and renders each field as a metric card, plus a hint on how to persist changes.
"""

from __future__ import annotations

from typing import Any

from aios.ui.components import (
    RenderContext,
    render_metric_card,
    render_section_header,
)


def _fmt_theme(v: Any) -> str:
    return str(v)


def _fmt_intensity(v: Any) -> str:
    return f"{v:.2f}"


def _fmt_bool(v: Any) -> str:
    return "yes" if v else "no"


def _fmt_interval(v: Any) -> str:
    return f"{v:.1f}s"


_FIELDS = (
    ("Theme", "theme", _fmt_theme),
    ("Accent Intensity", "accent_intensity", _fmt_intensity),
    ("Compact", "compact", _fmt_bool),
    ("Refresh Interval", "refresh_interval", _fmt_interval),
)


def render_settings_page(data: dict[str, Any], ctx: RenderContext) -> str:
    """Render the settings page mirroring the persisted ``ui`` section."""
    sections = [render_section_header(ctx, "Settings", tone="info")]

    if not data:
        sections.append(render_metric_card(ctx, "Settings", "no ui config", tone="warning"))
        return "\n".join(sections)

    for label, key, fmt in _FIELDS:
        value = data.get(key)
        if value is not None:
            sections.append(render_metric_card(ctx, label, fmt(value), tone="info"))

    sections.append(render_metric_card(ctx, "Persist", "aios ocean --save", tone="default"))
    return "\n".join(sections)
