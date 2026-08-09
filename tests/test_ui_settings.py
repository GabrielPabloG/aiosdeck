"""Tests for the settings page — UI section load/save and the ``--save`` flag.

Covers: reading the ``ui`` YAML section, atomic persistence that preserves
sibling sections, PyYAML-absent no-op behavior, malformed YAML tolerance, and
the ``aios ocean --save`` integration wiring.
"""

from __future__ import annotations

from pathlib import Path

from aios.ui.cli import _cmd_ocean
from aios.ui.datasources import settings_data
from aios.ui.settings_io import default_config_path, load_ui_section, save_ui_section
from aios.ui.settings_page import render_settings_page


class FakeKernel:
    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()

    def start(self, render_dashboard: bool = True) -> None:
        pass

    def status(self) -> dict[str, object]:
        return {"project": str(self.project_path), "engines": {}, "errors": []}

    def get_engine(self, name: str) -> None:
        return None


def _fake_kernel_factory(path: Path) -> FakeKernel:
    return FakeKernel(project_path=str(path))


# ── settings_io ───────────────────────────────────────────────────────────────


def test_load_ui_section_empty_when_missing(tmp_path: Path) -> None:
    assert load_ui_section(tmp_path / "config.yaml") == {}


def test_save_ui_section_preserves_sibling_sections(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "routing:\n"
        "  default_model: llama3\n"
        "  cost_cap: 0.05\n"
        "ui:\n"
        "  theme: dark\n"
    )
    save_ui_section(path, {"accent_intensity": 0.9, "compact": True, "refresh_interval": 3.0})

    text = path.read_text()
    assert "default_model: llama3" in text
    assert "cost_cap: 0.05" in text
    assert "accent_intensity: 0.9" in text
    assert "compact: true" in text
    assert "refresh_interval: 3.0" in text
    assert "theme: dark" not in text  # not in the provided ui dict


def test_save_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_ui_section(path, {"theme": "ocean"})
    assert load_ui_section(path) == {"theme": "ocean"}


def test_save_without_pyyaml_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("aios.ui.settings_io.YAML_AVAILABLE", False)
    path = tmp_path / "config.yaml"
    save_ui_section(path, {"theme": "ocean"})
    assert not path.exists()


def test_save_does_not_alter_file_when_pyyaml_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("aios.ui.settings_io.YAML_AVAILABLE", False)
    path = tmp_path / "config.yaml"
    path.write_text("routing:\n  default_model: llama3\n")
    save_ui_section(path, {"theme": "ocean"})
    assert "default_model: llama3" in path.read_text()


def test_malformed_yaml_does_not_break(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(":: not yaml ::\n  tab\tbroken")
    save_ui_section(path, {"theme": "ocean"})
    assert load_ui_section(path) == {"theme": "ocean"}


def test_default_config_path() -> None:
    p = default_config_path()
    assert p.name == "config.yaml"
    assert ".config" in p.parts and "aiosdeck" in p.parts


# ── settings_data / page ──────────────────────────────────────────────────────


def test_settings_data_returns_ui_section(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".config" / "aiosdeck" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("ui:\n  theme: ocean\n  compact: true\n")
    data = settings_data(FakeKernel())
    assert data["theme"] == "ocean"
    assert data["compact"] is True


def _ctx():
    from aios.ui import ColorResolver, RenderContext, ocean_theme

    return RenderContext(resolver=ColorResolver(ocean_theme, "auto"))


def test_render_settings_page_shows_fields() -> None:
    out = render_settings_page(
        {"theme": "ocean", "accent_intensity": 0.8, "compact": False, "refresh_interval": 2.0},
        _ctx(),
    )
    assert "Theme" in out
    assert "Accent Intensity" in out
    assert "--save" in out


def test_render_settings_page_empty_state() -> None:
    out = render_settings_page({}, _ctx())
    assert "no ui config" in out


# ── --save CLI integration ────────────────────────────────────────────────────


def test_cmd_ocean_save_writes_ui_section(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _cmd_ocean(["--page", "settings", "--once", "--save"], Path.cwd(), _fake_kernel_factory)
    cfg = tmp_path / ".config" / "aiosdeck" / "config.yaml"
    assert cfg.exists()
    assert "ui:" in cfg.read_text()


def test_cmd_ocean_without_save_does_not_write(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _cmd_ocean(["--page", "settings", "--once"], Path.cwd(), _fake_kernel_factory)
    cfg = tmp_path / ".config" / "aiosdeck" / "config.yaml"
    assert not cfg.exists()