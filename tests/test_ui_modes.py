"""Tests for aios.ui.mode — color mode detection and env precedence."""

from aios.ui import ColorMode, detect_color_mode

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
