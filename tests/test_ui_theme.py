"""Tests for aios.ui.theme and aios.ui.resolver — tokens and color codes."""

import pytest

from aios.ui import ColorMode, ColorResolver, Theme, ocean_theme


def test_resolver_truecolor_code():
    resolver = ColorResolver(ocean_theme, ColorMode.COLOR)
    assert resolver.enabled is True
    assert resolver.code("info") == "\x1b[38;2;56;189;248m"
    assert resolver.code("info", background=True) == "\x1b[48;2;56;189;248m"


def test_resolver_256_code():
    resolver = ColorResolver(ocean_theme, ColorMode.MODE_256)
    code = resolver.code("info")
    assert code.startswith("\x1b[38;5;")
    assert code.endswith("m")
    assert code[7:-1].isdigit()
    assert 0 <= int(code[7:-1]) <= 255


def test_resolver_256_background_code():
    resolver = ColorResolver(ocean_theme, ColorMode.MODE_256)
    assert resolver.code("info", background=True).startswith("\x1b[48;5;")


def test_resolver_mono_code_empty():
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    assert resolver.enabled is False
    assert resolver.code("info") == ""


def test_resolver_auto_code_empty():
    resolver = ColorResolver(ocean_theme, ColorMode.AUTO)
    assert resolver.enabled is False
    assert resolver.code("info") == ""


def test_resolver_paint_truecolor():
    resolver = ColorResolver(ocean_theme, ColorMode.COLOR)
    assert resolver.paint("ok", fg="success") == "\x1b[38;2;45;212;191mok\x1b[0m"


def test_resolver_paint_mono_unchanged():
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    assert resolver.paint("ok", fg="success") == "ok"


def test_resolver_marker_mono():
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    assert resolver.marker("info") == "*"
    assert resolver.marker("success") == "**"
    assert resolver.marker("danger") == "!!!"


def test_resolver_marker_empty_when_color_enabled():
    resolver = ColorResolver(ocean_theme, ColorMode.COLOR)
    assert resolver.marker("info") == ""


def test_resolver_marker_unknown_key_empty():
    resolver = ColorResolver(ocean_theme, ColorMode.MONO)
    assert resolver.marker("missing") == ""


def test_resolver_token_lookup():
    resolver = ColorResolver(ocean_theme, ColorMode.COLOR)
    assert resolver.token("info") == ocean_theme.accents["info"]
    assert resolver.token("background") == ocean_theme.background
    with pytest.raises(KeyError):
        resolver.token("missing")


def test_ocean_theme_defaults():
    assert ocean_theme.name == "ocean"
    assert ocean_theme.background == "#0b1420"
    assert ocean_theme.foreground == "#d7e6f2"


def test_ocean_theme_base_palette():
    assert ocean_theme.base == {
        "abyss": "#0b1420",
        "deep": "#10293c",
        "surf": "#123a52",
        "foam": "#1d5463",
        "sky": "#2a718e",
        "ice": "#9cc3d8",
    }


def test_ocean_theme_accent_palette():
    assert ocean_theme.accents == {
        "info": "#38bdf8",
        "success": "#2dd4bf",
        "warning": "#fbbf24",
        "danger": "#f87171",
    }


def test_ocean_theme_border_palette():
    assert ocean_theme.borders == {
        "subtle": "#14283f",
        "default": "#1e3a5f",
        "focused": "#38bdf8",
    }


def test_ocean_theme_tokens_are_six_digit_hex():
    tokens = [
        ocean_theme.background,
        ocean_theme.foreground,
        *ocean_theme.base.values(),
        *ocean_theme.accents.values(),
        *ocean_theme.borders.values(),
    ]
    for token in tokens:
        assert token.startswith("#")
        assert len(token) == 7


def test_resolver_token_order_base_over_accents():
    theme = Theme(
        name="t",
        background="#000000",
        foreground="#ffffff",
        base={"dup": "#111111"},
        accents={"dup": "#222222"},
        borders={"dup": "#333333"},
    )
    resolver = ColorResolver(theme, ColorMode.COLOR)
    assert resolver.token("dup") == "#111111"


def test_resolver_token_order_accents_over_borders():
    theme = Theme(
        name="t",
        background="#000000",
        foreground="#ffffff",
        accents={"dup": "#222222"},
        borders={"dup": "#333333"},
    )
    resolver = ColorResolver(theme, ColorMode.COLOR)
    assert resolver.token("dup") == "#222222"


def test_resolver_token_special_keys_beat_palettes():
    theme = Theme(
        name="t",
        background="#000000",
        foreground="#ffffff",
        base={"background": "#111111", "foreground": "#222222"},
    )
    resolver = ColorResolver(theme, ColorMode.COLOR)
    assert resolver.token("background") == "#000000"
    assert resolver.token("foreground") == "#ffffff"
