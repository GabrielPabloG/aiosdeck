"""Color mode selection for the AiosDeck console.

Defines the four-mode ``ColorMode`` capability enum and the
``detect_color_mode`` resolver that derives the effective mode from
environment variables (``NO_COLOR``, ``CLICOLOR``, ``FORCE_COLOR``,
``TERM``, ``COLORTERM``, ``AIOS_UI_*``) and the attached stream.
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from typing import IO


class ColorMode(Enum):
    """Color capability of the running console.

    ``AUTO`` is a preference, not a capability: resolve it through
    ``detect_color_mode`` before rendering. ``COLOR`` targets truecolor
    (24-bit) terminals, ``MODE_256`` the xterm-256 palette, and ``MONO``
    strips color and falls back to plain-text markers.
    """

    AUTO = "auto"
    COLOR = "color"
    MODE_256 = "256"
    MONO = "mono"


def detect_color_mode(stream: IO | None = None) -> ColorMode:
    """Resolve the effective color mode from environment and terminal.

    Precedence (highest first):
    1. ``NO_COLOR`` present and ``CLICOLOR=0`` are universal kill switches.
    2. ``AIOS_UI_COLORMODE`` / ``AIOS_UI_COLOR`` select a mode explicitly;
       ``auto`` (the default) falls through to environment detection.
    3. ``FORCE_COLOR=1|2|3`` forces color, 256-color or truecolor.
    4. The terminal is probed via ``COLORTERM``, ``TERM`` and TTY detection.
    5. Anything not detected as color-capable falls back to monochrome.
    """
    if os.environ.get("NO_COLOR") is not None:
        return ColorMode.MONO
    if os.environ.get("CLICOLOR") == "0":
        return ColorMode.MONO
    explicit = _explicit_mode()
    if explicit is not None and explicit is not ColorMode.AUTO:
        return explicit
    forced = _forced_color_mode()
    if forced is not None:
        return forced
    return _probe_terminal(stream)


def _probe_terminal(stream: IO | None) -> ColorMode:
    """Infer color capability from ``COLORTERM``, ``TERM`` and the stream."""
    term = os.environ.get("TERM", "").lower()
    if term == "dumb":
        return ColorMode.MONO
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in {"truecolor", "24bit"}:
        return ColorMode.COLOR
    if "256color" in term:
        return ColorMode.MODE_256
    if getattr(stream or sys.stdout, "isatty", lambda: False)():
        return ColorMode.COLOR
    if "color" in term:
        return ColorMode.COLOR
    return ColorMode.MONO


def _explicit_mode() -> ColorMode | None:
    """Return the mode requested via ``AIOS_UI_*``, or None when unset.

    Unknown values behave as ``AUTO`` so a stray variable never breaks the
    console.
    """
    raw = os.environ.get("AIOS_UI_COLORMODE") or os.environ.get("AIOS_UI_COLOR")
    if not raw:
        return None
    choices = {
        "auto": ColorMode.AUTO,
        "color": ColorMode.COLOR,
        "truecolor": ColorMode.COLOR,
        "true_color": ColorMode.COLOR,
        "ansi": ColorMode.COLOR,
        "on": ColorMode.COLOR,
        "256": ColorMode.MODE_256,
        "256color": ColorMode.MODE_256,
        "mono": ColorMode.MONO,
        "no_color": ColorMode.MONO,
        "none": ColorMode.MONO,
        "off": ColorMode.MONO,
    }
    return choices.get(raw.strip().lower(), ColorMode.AUTO)


_FORCE_OFF = 0
_FORCE_256 = 2
_FORCE_TRUECOLOR = 3


def _forced_color_mode() -> ColorMode | None:
    """Return the mode forced by ``FORCE_COLOR``, or None when not forced."""
    raw = os.environ.get("FORCE_COLOR")
    if raw is None:
        return None
    try:
        level = int(raw)
    except ValueError:
        level = 1
    if level <= _FORCE_OFF:
        return None
    if level >= _FORCE_TRUECOLOR:
        return ColorMode.COLOR
    if level == _FORCE_256:
        return ColorMode.MODE_256
    return ColorMode.COLOR
