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
from aios.ui.mode import ColorMode, detect_color_mode
from aios.ui.render import fit, is_compact, rule, terminal_size
from aios.ui.resolver import ColorResolver
from aios.ui.theme import Theme, ocean_theme

__all__ = [
    "ColorMode",
    "ColorResolver",
    "RenderContext",
    "Theme",
    "detect_color_mode",
    "fit",
    "is_compact",
    "ocean_theme",
    "render_metric_card",
    "render_panel",
    "render_progress",
    "render_section_header",
    "render_status_pill",
    "render_table",
    "rule",
    "terminal_size",
]
