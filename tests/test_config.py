import os

from aios.config.loader import ConfigLoader
from aios.config.schema import AiosDeckConfig


def test_defaults():
    config = AiosDeckConfig()
    assert config.runtime.adapter == "opencode"
    assert config.runtime.sandbox == "ai-jail"
    assert config.model.default == "ollama"
    assert config.logging.level == "INFO"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("AIOS_RUNTIME_ADAPTER", "custom")
    monkeypatch.setenv("AIOS_LOG_LEVEL", "DEBUG")

    config = AiosDeckConfig()
    config.runtime.adapter = os.environ["AIOS_RUNTIME_ADAPTER"]
    config.logging.level = os.environ["AIOS_LOG_LEVEL"]

    assert config.runtime.adapter == "custom"
    assert config.logging.level == "DEBUG"


def test_project_name_from_manifest(tmp_path):
    (tmp_path / ".aios").mkdir()
    (tmp_path / ".aios" / "project.yaml").write_text("name: test-project\nruntime: opencode\n")

    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()

    assert config.project.name == "test-project"
    assert config.runtime.adapter == "opencode"


def test_env_boolean_coercion(monkeypatch):
    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "true")
    loader = ConfigLoader()
    config = loader.load()
    assert config.memory.enabled is True

    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "false")
    config = loader.load()
    assert config.memory.enabled is False


def test_detection_fallback(tmp_path):
    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()
    assert config.project.name == tmp_path.name
