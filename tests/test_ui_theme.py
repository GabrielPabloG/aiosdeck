"""Tests for aios.ui.theme — color mode detection and token resolution."""

from pathlib import Path

import pytest

from aios.config.loader import ConfigLoader
from aios.config.schema import AiosDeckConfig
from aios.ui import (
    ColorMode,
    ColorResolver,
    Theme,
    detect_color_mode,
    ocean_theme,
)

_ENV_KEYS = (
    "NO_COLOR",
    "CLICOLOR",
    "FORCE_COLOR",
    "TERM",
    "COLORTERM",
    "AIOS_UI_COLORMODE",
    "AIOS_UI_COLOR",
)


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _clean_env(monkeypatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_enum_has_four_preferences():
    assert ColorMode.AUTO.value == "auto"
    assert ColorMode.COLOR.value == "color"
    assert ColorMode.MODE_256.value == "256"
    assert ColorMode.MONO.value == "mono"


def test_detect_defaults_to_mono(monkeypatch):
    _clean_env(monkeypatch)
    assert detect_color_mode() == ColorMode.MONO


def test_detect_no_color_wins(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_no_color_presence_wins_even_empty(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_no_color_beats_explicit_ui(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("AIOS_UI_COLORMODE", "color")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_clicolor_zero_disables(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CLICOLOR", "0")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_clicolor_other_value_ignored(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CLICOLOR", "1")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_colorterm_truecolor(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert detect_color_mode() == ColorMode.COLOR


def test_detect_colorterm_24bit(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("COLORTERM", "24bit")
    assert detect_color_mode() == ColorMode.COLOR


def test_detect_term_256color(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert detect_color_mode() == ColorMode.MODE_256


def test_detect_term_dumb_disables(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_tty_enables_color(monkeypatch):
    _clean_env(monkeypatch)
    assert detect_color_mode(_FakeStream(tty=True)) == ColorMode.COLOR


def test_detect_piped_output_stays_mono(monkeypatch):
    _clean_env(monkeypatch)
    assert detect_color_mode(_FakeStream(tty=False)) == ColorMode.MONO


def test_detect_force_color_levels(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert detect_color_mode() == ColorMode.COLOR
    monkeypatch.setenv("FORCE_COLOR", "2")
    assert detect_color_mode() == ColorMode.MODE_256
    monkeypatch.setenv("FORCE_COLOR", "3")
    assert detect_color_mode() == ColorMode.COLOR


def test_detect_force_color_zero_not_forced(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("FORCE_COLOR", "0")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_ui_colormode_explicit_256(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("AIOS_UI_COLORMODE", "256")
    assert detect_color_mode() == ColorMode.MODE_256


def test_detect_ui_color_alias_mono(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("AIOS_UI_COLOR", "mono")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_ui_colormode_auto_falls_back_to_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("AIOS_UI_COLORMODE", "auto")
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert detect_color_mode() == ColorMode.COLOR


def test_detect_ui_colormode_unknown_falls_back_to_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("AIOS_UI_COLORMODE", "banana")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert detect_color_mode() == ColorMode.MODE_256


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


def test_detect_no_color_beats_force_color(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "3")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_clicolor_zero_beats_force_color(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("CLICOLOR", "0")
    monkeypatch.setenv("FORCE_COLOR", "3")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_ui_explicit_beats_force_color(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("AIOS_UI_COLORMODE", "mono")
    monkeypatch.setenv("FORCE_COLOR", "3")
    assert detect_color_mode() == ColorMode.MONO


def test_detect_force_color_beats_term_dumb(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert detect_color_mode() == ColorMode.COLOR


def test_detect_force_color_256_beats_term_dumb(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "2")
    assert detect_color_mode() == ColorMode.MODE_256


def test_ui_config_defaults():
    config = AiosDeckConfig()
    assert config.ui.theme == "ocean"
    assert config.ui.accent_intensity == 0.8
    assert config.ui.compact is False
    assert config.ui.refresh_interval == 2.0
    assert config.ui.backlog_mode == "text"


def test_ui_default_theme_matches_ocean_theme():
    assert AiosDeckConfig().ui.theme == ocean_theme.name


def test_ui_env_overrides_defaults(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AIOS_UI_THEME", "midnight")
    monkeypatch.setenv("AIOS_UI_ACCENT_INTENSITY", "0.65")
    monkeypatch.setenv("AIOS_UI_COMPACT", "true")
    monkeypatch.setenv("AIOS_UI_REFRESH_INTERVAL", "1.5")

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.ui.theme == "midnight"
    assert config.ui.accent_intensity == 0.65
    assert config.ui.compact is True
    assert config.ui.refresh_interval == 1.5
    assert config._sources["ui.theme"] == "env:AIOS_UI_THEME"


def test_ui_env_violations_do_not_break_loader(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AIOS_UI_THEME", "not-a-theme")
    monkeypatch.setenv("AIOS_UI_ACCENT_INTENSITY", "9.5")
    monkeypatch.setenv("AIOS_UI_COMPACT", "banana")

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.ui.theme == "not-a-theme"
    assert config.ui.accent_intensity == 9.5
    assert config.ui.compact is False


def test_ui_package_survives_hostile_env(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "not-a-number")
    monkeypatch.setenv("AIOS_UI_COLORMODE", "banana")
    monkeypatch.setenv("AIOS_UI_THEME", "")

    import aios.ui  # noqa: F401  (import must not raise)

    assert aios.ui.ocean_theme.name == "ocean"
    assert aios.ui.Theme is Theme
    assert detect_color_mode() == ColorMode.MONO
