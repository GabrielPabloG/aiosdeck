"""AiosDeck UI — console themes, color modes and token resolution."""

from aios.ui.components import (
    RenderContext,
    render_metric_card,
    render_panel,
    render_progress,
    render_section_header,
    render_status_pill,
    render_table,
)
from aios.ui.datasources import (
    agents_data,
    knowledge_data,
    overview_data,
    quality_data,
    settings_data,
    skills_data,
    usage_data,
    workflows_data,
)
from aios.ui.mode import ColorMode, detect_color_mode
from aios.ui.pages import PAGE_NAMES, render_page
from aios.ui.render import fit, is_compact, rule, terminal_size
from aios.ui.resolver import ColorResolver
from aios.ui.theme import Theme, ocean_theme
from aios.ui.tui import run_tui

__all__ = [
    "ColorMode",
    "ColorResolver",
    "PAGE_NAMES",
    "RenderContext",
    "Theme",
    "agents_data",
    "detect_color_mode",
    "fit",
    "is_compact",
    "knowledge_data",
    "ocean_theme",
    "overview_data",
    "quality_data",
    "render_metric_card",
    "render_panel",
    "render_page",
    "render_progress",
    "render_section_header",
    "render_status_pill",
    "render_table",
    "rule",
    "run_tui",
    "settings_data",
    "skills_data",
    "terminal_size",
    "usage_data",
    "workflows_data",
]
