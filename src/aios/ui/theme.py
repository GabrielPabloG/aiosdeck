"""Ocean console theme — declarative design tokens.

The ocean theme is a dark, marine-inspired palette for the AiosDeck console:
deep-water backgrounds, cool accents, and high-contrast text. Tokens are
plain 6-digit hex strings; ``ColorResolver`` renders them for the active
``ColorMode``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    """Design tokens for the ocean console theme.

    ``base`` holds the core palette, ``accents`` high-emphasis semantic
    colors, and ``borders`` the chrome. All values are 6-digit hex strings
    unless ``MONO`` mode strips color entirely.
    """

    name: str
    background: str
    foreground: str
    base: dict[str, str] = field(default_factory=dict)
    accents: dict[str, str] = field(default_factory=dict)
    borders: dict[str, str] = field(default_factory=dict)


ocean_theme = Theme(
    name="ocean",
    background="#0b1420",
    foreground="#d7e6f2",
    base={
        "abyss": "#0b1420",
        "deep": "#10293c",
        "surf": "#123a52",
        "foam": "#1d5463",
        "sky": "#2a718e",
        "ice": "#9cc3d8",
    },
    accents={
        "info": "#38bdf8",
        "success": "#2dd4bf",
        "warning": "#fbbf24",
        "danger": "#f87171",
    },
    borders={
        "subtle": "#14283f",
        "default": "#1e3a5f",
        "focused": "#38bdf8",
    },
)
