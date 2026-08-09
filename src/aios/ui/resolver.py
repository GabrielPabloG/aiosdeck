"""Token resolution — turn ``Theme`` tokens into terminal output.

``ColorResolver`` emits truecolor (24-bit) or xterm-256 escape codes for a
``ColorMode``, and in ``MONO`` mode replaces color with plain-text markers
so semantic emphasis survives on monochrome terminals.
"""

from __future__ import annotations

from aios.ui.mode import ColorMode
from aios.ui.theme import Theme

_HEX_DIGITS = 6


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Parse a ``#rrggbb`` / ``rrggbb`` hex color into an RGB tuple."""
    value = color.lstrip("#")
    if len(value) != _HEX_DIGITS:
        raise ValueError(f"expected a 6-digit hex color, got {color!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


_ANSI16 = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)

_256_CUBE = (0, 95, 135, 175, 215, 255)
_256_GRAY_START = 232
_256_GRAY_RANGE = range(8, 238, 10)


def _closest_index(value: int, levels: tuple[int, ...]) -> int:
    """Return the index of the palette level nearest to ``value``."""
    return min(range(len(levels)), key=lambda i: (levels[i] - value) ** 2)


def _nearest_xterm256(color: str) -> int:
    """Map a hex color to the closest xterm-256 palette index (0-255)."""
    r, g, b = _hex_to_rgb(color)
    best, best_dist = 0, 3 * 255 * 255
    for index, (sr, sg, sb) in enumerate(_ANSI16):
        dist = (r - sr) ** 2 + (g - sg) ** 2 + (b - sb) ** 2
        if dist < best_dist:
            best, best_dist = index, dist
    ri, gi, bi = (_closest_index(value, _256_CUBE) for value in (r, g, b))
    index = 16 + 36 * ri + 6 * gi + bi
    dist = (r - _256_CUBE[ri]) ** 2 + (g - _256_CUBE[gi]) ** 2 + (b - _256_CUBE[bi]) ** 2
    if dist < best_dist:
        best, best_dist = index, dist
    for i, value in enumerate(_256_GRAY_RANGE):
        dist = (r - value) ** 2 + (g - value) ** 2 + (b - value) ** 2
        if dist < best_dist:
            best, best_dist = _256_GRAY_START + i, dist
    return best


_MONO_MARKERS: dict[str, str] = {
    "info": "*",
    "success": "**",
    "warning": "!",
    "danger": "!!!",
    "focused": ">",
}


class ColorResolver:
    """Resolve ``Theme`` tokens to render output for a ``ColorMode``."""

    def __init__(self, theme: Theme, mode: ColorMode) -> None:
        self.theme = theme
        self.mode = mode

    @property
    def enabled(self) -> bool:
        """True when the mode can emit color codes."""
        return self.mode in {ColorMode.COLOR, ColorMode.MODE_256}

    def token(self, key: str) -> str:
        """Look up a raw token value across base, accents and borders."""
        if key == "background":
            return self.theme.background
        if key == "foreground":
            return self.theme.foreground
        for palette in (self.theme.base, self.theme.accents, self.theme.borders):
            if key in palette:
                return palette[key]
        raise KeyError(key)

    def code(self, key: str, *, background: bool = False) -> str:
        """Emit the ANSI escape code for a token key, or ``""`` when off.

        ``COLOR`` mode emits 24-bit truecolor codes (``38;2;R;G;B``) and
        ``MODE_256`` the nearest xterm-256 index (``38;5;N``).
        """
        slot = 48 if background else 38
        if self.mode is ColorMode.COLOR:
            r, g, b = _hex_to_rgb(self.token(key))
            return f"\033[{slot};2;{r};{g};{b}m"
        if self.mode is ColorMode.MODE_256:
            return f"\033[{slot};5;{_nearest_xterm256(self.token(key))}m"
        return ""

    def marker(self, key: str) -> str:
        """Return a plain-text marker for a token in ``MONO`` mode.

        Monochrome has no color to carry semantic emphasis, so the resolver
        revisits ASCII markers (asterisks and punctuation) that callers may
        render in place of a colored token. Empty when colors are available.
        """
        if self.mode is not ColorMode.MONO:
            return ""
        return _MONO_MARKERS.get(key, "")

    def paint(self, text: str, *, fg: str | None = None, bg: str | None = None) -> str:
        """Wrap ``text`` in ANSI color codes; unchanged when colors are off."""
        prefix = ""
        if fg is not None:
            prefix += self.code(fg, background=False)
        if bg is not None:
            prefix += self.code(bg, background=True)
        if not prefix:
            return text
        return f"{prefix}{text}\033[0m"
