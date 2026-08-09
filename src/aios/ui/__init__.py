"""AiosDeck UI — console themes, color modes and token resolution."""

from aios.ui.mode import ColorMode, detect_color_mode
from aios.ui.resolver import ColorResolver
from aios.ui.theme import Theme, ocean_theme

__all__ = [
    "ColorMode",
    "ColorResolver",
    "Theme",
    "detect_color_mode",
    "ocean_theme",
]
