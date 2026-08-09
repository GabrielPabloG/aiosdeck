"""Tests for aios.ui.components — golden snapshots, mono mode and source purity.

Exercises every ``render_*`` widget in its normal, focused and compact variants
against the fixed-width-80 golden ``SNAPSHOTS`` from ``tests.ui_snapshots``. A
NO_COLOR → ``MONO`` scenario exercises ``detect_color_mode`` end to end and
asserts no ANSI or hex value leaks out of the composable widgets.
"""

from pathlib import Path

import pytest

from aios.ui import (
    ColorMode,
    ColorResolver,
    RenderContext,
    components,
    detect_color_mode,
    ocean_theme,
    render_status_pill,
    render,
)
from tests.ui_snapshots import ANSI_RE, HEX_RE, SNAPSHOTS, WIDGET_CASES, clean_env, render_widget


@pytest.mark.parametrize("comp,variant", WIDGET_CASES)
def test_render_snapshot_mono_width_80(comp, variant):
    output = render_widget(ColorMode.MONO, comp, variant)
    assert output == SNAPSHOTS[comp][variant][0]
    assert "\x1b[" not in output
    assert HEX_RE.search(output) is None
    for line in output.splitlines():
        assert len(line) <= 80


@pytest.mark.parametrize("comp,variant", WIDGET_CASES)
def test_render_snapshot_color_width_80(comp, variant):
    output = render_widget(ColorMode.COLOR, comp, variant)
    assert output == SNAPSHOTS[comp][variant][1]
    for line in output.splitlines():
        assert len(ANSI_RE.sub("", line)) <= 80
    if variant != "compact":
        assert ANSI_RE.search(output) is not None


@pytest.mark.parametrize("mode", [ColorMode.MONO, ColorMode.COLOR])
def test_panel_golden_frame_fits_exactly_80(mode):
    framed = [ANSI_RE.sub("", line) for line in render_widget(mode, "panel", "normal").splitlines()]
    assert len(framed[0]) == 80
    assert len(framed[-1]) == 80
    assert framed[0] == framed[-1].replace("└", "┌").replace("┘", "┐")


def test_panel_focus_border_differs_from_default():
    assert render_widget(ColorMode.COLOR, "panel", "focus") != render_widget(
        ColorMode.COLOR, "panel", "normal"
    )
    assert "\x1b[38;2;56;189;248m" in render_widget(ColorMode.COLOR, "panel", "focus")
    assert "\x1b[38;2;30;58;95m" in render_widget(ColorMode.COLOR, "panel", "normal")


def test_status_pill_tone_uses_background_in_wide_layout():
    pink = render_status_pill(
        RenderContext(resolver=ColorResolver(ocean_theme, ColorMode.COLOR)), "x", tone="danger"
    )
    assert pink.startswith("\x1b[48;2;248;113;113m")
    plain = render_widget(ColorMode.MONO, "status", "normal")
    assert plain == " ready "


@pytest.mark.parametrize("comp", SNAPSHOTS)
@pytest.mark.parametrize("variant", ["normal", "focus", "compact"])
def test_no_color_renders_without_ansi_or_hex(monkeypatch, comp, variant):
    clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    output = render_widget(detect_color_mode(), comp, variant)
    assert ANSI_RE.search(output) is None
    assert "\x1b[" not in output
    assert HEX_RE.search(output) is None
    assert output == SNAPSHOTS[comp][variant][0]


def test_widget_source_has_no_hardcoded_ansi_or_hex():
    for module in (components, render):
        source = Path(module.__file__).read_text()
        assert ANSI_RE.search(source) is None
        assert "\x1b[" not in source
        assert HEX_RE.search(source) is None
