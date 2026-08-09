"""Golden snapshots and render helpers shared by the aios.ui widget tests.

This module is intentionally not prefixed with ``test_`` so pytest never
collects it as a test module. It owns the fixed-width-80 golden strings for
every ``render_*`` widget in its normal, focused and compact variants.
"""

import re

from aios.ui import (
    ColorMode,
    ColorResolver,
    RenderContext,
    ocean_theme,
    render_metric_card,
    render_panel,
    render_progress,
    render_section_header,
    render_status_pill,
    render_table,
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

ENV_KEYS = (
    "NO_COLOR",
    "CLICOLOR",
    "FORCE_COLOR",
    "TERM",
    "COLORTERM",
    "AIOS_UI_COLORMODE",
    "AIOS_UI_COLOR",
)

_PANEL_MONO = "\n".join(
    (
        "┌──────────────────────────────────────────────────────────────────────────────┐",
        "│ Build                                                                        │",
        "│ ok                                                                           │",
        "└──────────────────────────────────────────────────────────────────────────────┘",
    )
)
_PANEL_COLOR_DEFAULT = "\n".join(
    (
        "\x1b[38;2;30;58;95m┌──────────────────────────────────────────────────────────────────────────────┐\x1b[0m",
        "\x1b[38;2;30;58;95m│ Build                                                                        │\x1b[0m",
        "\x1b[38;2;30;58;95m│ ok                                                                           │\x1b[0m",
        "\x1b[38;2;30;58;95m└──────────────────────────────────────────────────────────────────────────────┘\x1b[0m",
    )
)
_PANEL_COLOR_FOCUSED = "\n".join(
    (
        "\x1b[38;2;56;189;248m┌──────────────────────────────────────────────────────────────────────────────┐\x1b[0m",
        "\x1b[38;2;56;189;248m│ Build                                                                        │\x1b[0m",
        "\x1b[38;2;56;189;248m│ ok                                                                           │\x1b[0m",
        "\x1b[38;2;56;189;248m└──────────────────────────────────────────────────────────────────────────────┘\x1b[0m",
    )
)
_METRIC_MONO = "\n".join(
    (
        "┌──────────────────────────────────────────────────────────────────────────────┐",
        "│ CPU: 42%                                                                     │",
        "└──────────────────────────────────────────────────────────────────────────────┘",
    )
)
_METRIC_COLOR_FOCUSED = "\n".join(
    (
        "\x1b[38;2;56;189;248m┌──────────────────────────────────────────────────────────────────────────────┐\x1b[0m",
        "\x1b[38;2;56;189;248m│\x1b[0m CPU: 42%                                                                     \x1b[38;2;56;189;248m│\x1b[0m",
        "\x1b[38;2;56;189;248m└──────────────────────────────────────────────────────────────────────────────┘\x1b[0m",
    )
)

SNAPSHOTS = {
    "panel": {
        "normal": (_PANEL_MONO, _PANEL_COLOR_DEFAULT),
        "focus": (_PANEL_MONO, _PANEL_COLOR_FOCUSED),
        "compact": ("Build ok", "\x1b[38;2;30;58;95mBuild ok\x1b[0m"),
    },
    "progress": {
        "normal": (
            "Training ██████████░░░░░░░░░░ 50%",
            "Training \x1b[38;2;56;189;248m██████████░░░░░░░░░░\x1b[0m 50%",
        ),
        "focus": (
            "Training ██████████░░░░░░░░░░ 50%",
            "Training \x1b[38;2;56;189;248m██████████░░░░░░░░░░\x1b[0m 50%",
        ),
        "compact": ("Training 50%", "Training 50%"),
    },
    "status": {
        "normal": (" ready ", "\x1b[48;2;56;189;248m ready \x1b[0m"),
        "focus": (" ready ", "\x1b[48;2;56;189;248m ready \x1b[0m"),
        "compact": ("<ready>", "\x1b[38;2;56;189;248m<ready>\x1b[0m"),
    },
    "metric": {
        "normal": (_METRIC_MONO, _METRIC_COLOR_FOCUSED),
        "focus": (_METRIC_MONO, _METRIC_COLOR_FOCUSED),
        "compact": ("CPU: 42%", "\x1b[38;2;56;189;248mCPU: 42%\x1b[0m"),
    },
    "section": {
        "normal": (
            "Progress\n────────────────────────────────────────────────────────────────────────────────",
            "\x1b[38;2;56;189;248mProgress\x1b[0m\n"
            "\x1b[38;2;30;58;95m────────────────────────────────────────────────────────────────────────────────\x1b[0m",
        ),
        "focus": (
            "Progress\n────────────────────────────────────────────────────────────────────────────────",
            "\x1b[38;2;56;189;248mProgress\x1b[0m\n"
            "\x1b[38;2;30;58;95m────────────────────────────────────────────────────────────────────────────────\x1b[0m",
        ),
        "compact": ("· Progress", "\x1b[38;2;56;189;248m· Progress\x1b[0m"),
    },
    "table": {
        "normal": (
            "name  status\n────────────\nui    ok    \ncore  warn  ",
            "\x1b[38;2;56;189;248mname  status\x1b[0m\n"
            "\x1b[38;2;30;58;95m────────────\x1b[0m\n"
            "ui    ok    \n"
            "core  warn  ",
        ),
        "focus": (
            "name  status\n────────────\nui    ok    \ncore  warn  ",
            "\x1b[38;2;56;189;248mname  status\x1b[0m\n"
            "\x1b[38;2;30;58;95m────────────\x1b[0m\n"
            "ui    ok    \n"
            "core  warn  ",
        ),
        "compact": (
            "name status\nui   ok    \ncore warn  ",
            "\x1b[38;2;56;189;248mname status\x1b[0m\nui   ok    \ncore warn  ",
        ),
    },
}

WIDGET_CASES = [(comp, variant) for comp in SNAPSHOTS for variant in ("normal", "focus", "compact")]


def render_widget(mode: ColorMode, comp: str, variant: str) -> str:
    resolver = ColorResolver(ocean_theme, mode)
    context = RenderContext(width=80, height=24, resolver=resolver, compact=variant == "compact")
    if comp == "panel":
        border = "focused" if variant == "focus" else "default"
        return render_panel(context, title="Build", body="ok", border=border)
    if comp == "progress":
        tone = "focused" if variant == "focus" else "info"
        return render_progress(context, "Training", 0.5, tone=tone)
    if comp == "status":
        tone = "focused" if variant == "focus" else "info"
        return render_status_pill(context, "ready", tone=tone)
    if comp == "metric":
        tone = "focused" if variant == "focus" else "info"
        return render_metric_card(context, "CPU", "42%", tone=tone)
    if comp == "section":
        tone = "focused" if variant == "focus" else "info"
        return render_section_header(context, "Progress", tone=tone)
    if comp == "table":
        tone = "focused" if variant == "focus" else "info"
        return render_table(
            context, ["name", "status"], [["ui", "ok"], ["core", "warn"]], tone=tone
        )
    raise AssertionError(f"unknown component {comp!r}")


def clean_env(monkeypatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
