"""Tests for aios.ui config wiring — defaults, env overrides and hostile env."""

from pathlib import Path

from aios.config.loader import ConfigLoader
from aios.config.schema import AiosDeckConfig
from aios.ui import ColorMode, Theme, detect_color_mode, ocean_theme

_ENV_KEYS = (
    "NO_COLOR",
    "CLICOLOR",
    "FORCE_COLOR",
    "TERM",
    "COLORTERM",
    "AIOS_UI_COLORMODE",
    "AIOS_UI_COLOR",
    "AIOS_UI_THEME",
    "AIOS_UI_ACCENT_INTENSITY",
    "AIOS_UI_COMPACT",
    "AIOS_UI_REFRESH_INTERVAL",
)


def _clean_env(monkeypatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


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
