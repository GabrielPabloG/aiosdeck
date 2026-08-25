"""Config loader mapping tables, source tracking, coercion, and YAML I/O."""

import logging
import os
from pathlib import Path
from unittest import mock

import pytest
import yaml

import aios.config.loader as loader_module
from aios.config.loader import ConfigLoader


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in list(os.environ):
        if var.startswith("AIOS_"):
            monkeypatch.delenv(var)


def _resolve(obj, field_path):
    for part in field_path.split("."):
        obj = getattr(obj, part)
    return obj


ENV_CASES = [
    ("AIOS_RUNTIME_ADAPTER", "runtime.adapter", "custom-adapter"),
    ("AIOS_SANDBOX", "runtime.sandbox", "boxed"),
    ("AIOS_RUNTIME_COMMAND", "runtime.command", "run it"),
    ("AIOS_DEFAULT_MODEL", "model.default", "gpt-x"),
    ("AIOS_OLLAMA_MODEL", "model.ollama_model", "llama99"),
    ("AIOS_OLLAMA_HOST", "model.ollama_host", "http://host:1"),
    ("AIOS_MEMORY_ENABLED", "memory.enabled", "true", True),
    ("AIOS_MEMORY_PATH", "memory.path", "/tmp/mem.db"),
    ("AIOS_SECURITY_ENABLED", "security.enabled", "true", True),
    ("AIOS_LOG_LEVEL", "logging.level", "DEBUG"),
    ("AIOS_AUDIT_PATH", "logging.audit_path", "/tmp/audit.log"),
    ("AIOS_LEARNING_ENABLED", "learning.enabled", "true", True),
    ("AIOS_PROJECT_NAME", "project.name", "proj-x"),
    ("AIOS_PROJECTS_DIR", "project.directory", "~/work"),
    ("AIOS_ROUTING_ENABLED", "routing.enabled", "true", True),
    ("AIOS_ROUTING_COST_CAP", "routing.cost_cap", "0.42", 0.42),
    ("AIOS_UI_THEME", "ui.theme", "desert"),
    ("AIOS_UI_ACCENT_INTENSITY", "ui.accent_intensity", "0.33", 0.33),
    ("AIOS_UI_COMPACT", "ui.compact", "true", True),
    ("AIOS_UI_REFRESH_INTERVAL", "ui.refresh_interval", "9.5", 9.5),
]

ENV_PARAMS = [
    (env_var, field_path, raw, case[3] if len(case) == 4 else raw)
    for case in ENV_CASES
    for env_var, field_path, raw in [case[:3]]
]


@pytest.mark.parametrize("case", ENV_PARAMS)
def test_env_mapping_applied_with_source(case, monkeypatch, tmp_path):
    env_var, field_path, raw, expected = case
    monkeypatch.setenv(env_var, raw)

    config = ConfigLoader(project_path=tmp_path).load()

    assert _resolve(config, field_path) == expected, field_path
    assert config._sources[field_path] == f"env:{env_var}"


USER_YAML_CASES = [
    ("runtime", "adapter", "runtime.adapter", "u-adapter"),
    ("runtime", "sandbox", "runtime.sandbox", "u-box"),
    ("runtime", "command", "runtime.command", "u-cmd"),
    ("model", "default", "model.default", "u-model"),
    ("model", "ollama_model", "model.ollama_model", "u-ollama"),
    ("model", "ollama_host", "model.ollama_host", "http://u:1234"),
    ("memory", "enabled", "memory.enabled", False),
    ("memory", "path", "memory.path", "u/memory.db"),
    ("security", "enabled", "security.enabled", False),
    ("security", "policies_dir", "security.policies_dir", "u/policies"),
    ("quality", "enabled", "quality.enabled", False),
    ("quality", "auto_detect", "quality.auto_detect", False),
    ("quality", "environment", "quality.environment", "staging"),
    ("quality", "policy", "quality.policy", {"release": ["high"]}),
    ("quality", "overrides", "quality.overrides", [{"gate": "g"}]),
    ("logging", "level", "logging.level", "WARNING"),
    ("logging", "audit_path", "logging.audit_path", "u/audit.log"),
    ("learning", "enabled", "learning.enabled", False),
    ("learning", "auto_capture", "learning.auto_capture", False),
    ("learning", "confidence_threshold", "learning.confidence_threshold", 0.77),
    ("learning", "min_evidence", "learning.min_evidence", 3),
    ("learning", "recurrence_threshold", "learning.recurrence_threshold", 4),
    ("learning", "policy", "learning.policy", {"x": "y"}),
    ("routing", "enabled", "routing.enabled", False),
    ("routing", "default_provider", "routing.default_provider", "openrouter"),
    ("routing", "default_model", "routing.default_model", "deepseek"),
    ("routing", "default_variant", "routing.default_variant", "official"),
    ("routing", "rules", "routing.rules", [{"agent": "dev"}]),
    ("routing", "cost_cap", "routing.cost_cap", 0.5),
    ("routing", "context_limits", "routing.context_limits", {"dev": 100}),
    ("routing", "fallback_providers", "routing.fallback_providers", [{"provider": "p"}]),
    ("project", "name", "project.name", "yaml-proj"),
    ("project", "directory", "project.directory", "~/yaml-dir"),
    ("ui", "theme", "ui.theme", "nord"),
    ("ui", "accent_intensity", "ui.accent_intensity", 0.11),
    ("ui", "compact", "ui.compact", True),
    ("ui", "refresh_interval", "ui.refresh_interval", 7.5),
]


def test_user_config_all_sections_applied_with_source(tmp_path):
    data = {}
    for section, key, _field_path, value in USER_YAML_CASES:
        data.setdefault(section, {})[key] = value
    config_dir = tmp_path / ".config" / "aiosdeck"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(yaml.safe_dump(data))

    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()
    source = str(config_dir / "config.yaml")

    for _section, _key, field_path, value in USER_YAML_CASES:
        assert _resolve(config, field_path) == value, field_path
        assert config._sources[field_path] == source, field_path


def test_user_config_ignores_non_dict_sections_and_null_values(tmp_path):
    config_dir = tmp_path / ".config" / "aiosdeck"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("ui: not-a-dict\nmodel:\n  default: null\n")

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.ui.theme == "ocean"
    assert config.model.default == "ollama"
    assert "ui.theme" not in config._sources
    assert config.project.name == tmp_path.name


MANIFEST_ROUTING_VALUES = {
    "enabled": False,
    "default_provider": "openrouter",
    "default_model": "deepseek-v4",
    "default_variant": "official",
    "rules": [{"agent": "dev", "model": "m"}],
    "cost_cap": 0.25,
    "context_limits": {"dev": 500},
    "fallback_providers": [{"provider": "ollama"}],
}


def test_project_manifest_full_mapping_with_sources(tmp_path):
    (tmp_path / ".aios").mkdir()
    manifest = {
        "name": "manifest-proj",
        "runtime": "opencode",
        "sandbox": "jail",
        "skills": ["a", "b"],
        "routing": dict(MANIFEST_ROUTING_VALUES),
    }
    (tmp_path / ".aios" / "project.yaml").write_text(yaml.safe_dump(manifest))

    config = ConfigLoader(project_path=tmp_path).load()
    source = str(tmp_path / ".aios" / "project.yaml")

    assert config.project.name == "manifest-proj"
    assert config.runtime.adapter == "opencode"
    assert config.runtime.sandbox == "jail"
    assert config.project.skills == ["a", "b"]
    for key, value in MANIFEST_ROUTING_VALUES.items():
        assert getattr(config.routing, key) == value, key
    tracked = [
        "project.name",
        "runtime.adapter",
        "runtime.sandbox",
        "project.skills",
        *(f"routing.{key}" for key in MANIFEST_ROUTING_VALUES),
    ]
    for field_path in tracked:
        assert config._sources[field_path] == source, field_path


def test_manifest_ignores_null_values(tmp_path):
    (tmp_path / ".aios").mkdir()
    (tmp_path / ".aios" / "project.yaml").write_text("name: null\nskills: not-a-list\n")

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.project.name == tmp_path.name
    assert config.project.skills == []
    assert list(config._sources) == ["project.name"]


def test_detection_records_source(tmp_path):
    config = ConfigLoader(project_path=tmp_path).load()

    assert config.project.name == tmp_path.name
    assert config._sources["project.name"] == "detection"


class _Leaf:
    label = ""


class _Mid:
    def __init__(self):
        self.leaf = _Leaf()


class _Root:
    def __init__(self):
        self.mid = _Mid()


def test_set_field_supports_deep_paths():
    loader = ConfigLoader()
    root = _Root()

    loader._set_field(root, "mid.leaf.label", "deep", "unit-src")

    assert root.mid.leaf.label == "deep"
    assert loader._sources["mid.leaf.label"] == "unit-src"


def test_set_field_skips_unknown_leaf():
    loader = ConfigLoader()
    root = _Root()

    loader._set_field(root, "mid.missing", "v", "s")

    assert loader._sources == {}


def test_coerce_accepts_numeric_and_yes_booleans(monkeypatch):
    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "1")
    assert ConfigLoader().load().memory.enabled is True

    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "yes")
    assert ConfigLoader().load().memory.enabled is True

    monkeypatch.setenv("AIOS_UI_COMPACT", "YES")
    assert ConfigLoader().load().ui.compact is True

    monkeypatch.setenv("AIOS_UI_COMPACT", "no")
    assert ConfigLoader().load().ui.compact is False


def test_load_yaml_debug_message_when_yaml_unavailable(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(loader_module, "YAML_AVAILABLE", False)
    path = tmp_path / "x.yaml"

    with caplog.at_level(logging.DEBUG, logger="aios.config"):
        assert ConfigLoader()._load_yaml(path) is None

    record = next(r for r in caplog.records if r.levelno == logging.DEBUG)
    assert record.getMessage() == f"PyYAML not installed, skipping {path}"


def test_load_yaml_warning_message_on_read_error(tmp_path, caplog):
    path = tmp_path / "config.yaml"

    def broken_open(file, *args, **kwargs):
        raise OSError(5, "boom")

    with (
        mock.patch("builtins.open", side_effect=broken_open),
        caplog.at_level(logging.WARNING, logger="aios.config"),
    ):
        assert ConfigLoader()._load_yaml(path) is None

    record = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert record.getMessage() == f"Failed to load {path}: [Errno 5] boom"
