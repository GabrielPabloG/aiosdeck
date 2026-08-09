"""Tests for aios.ui.render — layout helpers and RenderContext geometry."""

import pytest

from aios.ui import (
    ColorMode,
    ColorResolver,
    RenderContext,
    fit,
    is_compact,
    ocean_theme,
    render_panel,
    rule,
)


def test_compact_render_context_drops_chrome():
    mono = ColorResolver(ocean_theme, ColorMode.MONO)
    wide = RenderContext(width=80, height=24, resolver=mono)
    narrow = RenderContext(width=40, height=24, resolver=mono)
    assert render_panel(wide, title="T", body="b") != render_panel(narrow, title="T", body="b")
    assert render_panel(narrow, title="T", body="b") == "T b"


def test_render_context_requires_resolver():
    with pytest.raises(TypeError):
        RenderContext()


def test_render_context_derives_compact_from_geometry():
    mono = ColorResolver(ocean_theme, ColorMode.MONO)
    assert RenderContext(width=80, height=24, resolver=mono).compact is False
    assert RenderContext(width=40, height=10, resolver=mono).compact is True


def test_render_context_explicit_compact_wins():
    mono = ColorResolver(ocean_theme, ColorMode.MONO)
    forced = RenderContext(width=80, height=24, resolver=mono, compact=True)
    assert forced.compact is True
    assert render_panel(forced, title="T", body="b") == "T b"
    spacious = RenderContext(width=40, height=10, resolver=mono, compact=False)
    assert spacious.compact is False


def test_is_compact_threshold():
    assert is_compact(80, 24) is False
    assert is_compact(80, 23) is True
    assert is_compact(79, 24) is True
    assert is_compact(40, 10) is True


def test_fit_passthrough_and_truncation():
    assert fit("short", 80) == "short"
    assert fit("long text", 5) == "long…"
    assert fit("long text", 4) == "lon…"
    assert fit("long text", 1) == "…"
    assert fit("long text", 0) == ""
    assert fit("long text", -3) == ""


def test_rule_width_and_validation():
    assert rule("─", 80) == "─" * 80
    assert rule("-", 4) == "----"
    assert rule("─", 0) == ""
    with pytest.raises(ValueError):
        rule("ab")
