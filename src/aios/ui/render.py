"""Terminal layout helpers — sizing, text fitting and separators.

Pure functions with no global state. ``terminal_size`` prefers explicit
dimensions, then an injectable probe (``shutil.get_terminal_size`` by
default) paired with a configurable fallback so tests stay deterministic.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable

_DEFAULT_WIDTH = 80
_DEFAULT_HEIGHT = 24
_COMPACT_WIDTH = 80
_COMPACT_HEIGHT = 24

_ELLIPSIS = "…"

#: Probes return an ``os.terminal_size`` from an optional fallback size.
TerminalProbe = Callable[[tuple[int, int] | None], os.terminal_size]


def terminal_size(
    width: int | None = None,
    height: int | None = None,
    *,
    fallback: tuple[int, int] = (_DEFAULT_WIDTH, _DEFAULT_HEIGHT),
    probe: TerminalProbe = shutil.get_terminal_size,
) -> os.terminal_size:
    """Resolve terminal dimensions, honoring explicit overrides.

    ``width`` / ``height`` win over the probe result when given. Otherwise
    the size is measured through ``probe`` (default
    ``shutil.get_terminal_size``) and falls back to ``fallback`` when the
    terminal cannot be queried (e.g. piped output).
    """
    detected = probe(fallback)
    return os.terminal_size(
        (
            width if width is not None else detected.columns,
            height if height is not None else detected.lines,
        )
    )


def fit(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` columns, suffixing an ellipsis.

    Shorter text is returned unchanged; a single-column fit collapses to
    just the ellipsis; a non-positive width yields an empty string.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return _ELLIPSIS
    return text[: width - 1] + _ELLIPSIS


def rule(char: str = "─", width: int | None = None) -> str:
    """Build a horizontal separator line of ``char`` repeated ``width`` times.

    ``width`` defaults to the full terminal width. ``char`` must be a single
    character, so the separator has one unambiguous width.
    """
    if len(char) != 1:
        raise ValueError(f"expected a single character, got {char!r}")
    if width is None:
        width = terminal_size().columns
    if width <= 0:
        return ""
    return char * width


def is_compact(width: int, height: int) -> bool:
    """True when the console is too small for a spacious layout.

    Matches the layout threshold: narrow (< ``80`` columns) or short
    (< ``24`` lines) consoles are considered compact.
    """
    return width < _COMPACT_WIDTH or height < _COMPACT_HEIGHT
