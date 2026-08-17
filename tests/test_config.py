import json
import os
from pathlib import Path

from aios.config.loader import ConfigLoader
from aios.config.schema import AiosDeckConfig


PROJECT_ROOT = Path(__file__).parents[1]


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


def test_project_manifest_runtime_wins_over_ollama_adapter_env(tmp_path, monkeypatch):
    (tmp_path / ".aios").mkdir()
    (tmp_path / ".aios" / "project.yaml").write_text("runtime: opencode\n")
    monkeypatch.setenv("AIOS_RUNTIME_ADAPTER", "ollama")

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.runtime.adapter == "opencode"


def test_project_manifest_sets_reproducible_routing_defaults(tmp_path):
    (tmp_path / ".aios").mkdir()
    (tmp_path / ".aios" / "project.yaml").write_text(
        "runtime: opencode\nrouting:\n  default_provider: ollama\n  default_model: llama3.2\n"
    )

    config = ConfigLoader(project_path=tmp_path).load()

    assert config.routing.default_provider == "ollama"
    assert config.routing.default_model == "llama3.2"


def test_project_opencode_config_registers_default_provider():
    config_path = PROJECT_ROOT / ".opencode" / "opencode.json"
    config = json.loads(config_path.read_text())
    providers = config["provider"]
    assert "qwen-hf" in providers
    provider = providers["qwen-hf"]

    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"].get("apiKey") in (None, "none")
    assert "Qwen/Qwen3.8-27B" in provider["models"]
    assert not any(
        secret_name in json.dumps(provider).lower() for secret_name in ("token", "password")
    )


def test_env_boolean_coercion(monkeypatch):
    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "true")
    loader = ConfigLoader()
    config = loader.load()
    assert config.memory.enabled is True

    monkeypatch.setenv("AIOS_MEMORY_ENABLED", "false")
    config = loader.load()
    assert config.memory.enabled is False


def test_env_ui_coercion(monkeypatch):
    monkeypatch.setenv("AIOS_UI_THEME", "midnight")
    monkeypatch.setenv("AIOS_UI_ACCENT_INTENSITY", "0.65")
    monkeypatch.setenv("AIOS_UI_COMPACT", "true")
    monkeypatch.setenv("AIOS_UI_REFRESH_INTERVAL", "1.5")
    loader = ConfigLoader()
    config = loader.load()
    assert config.ui.theme == "midnight"
    assert config.ui.accent_intensity == 0.65
    assert config.ui.compact is True
    assert config.ui.refresh_interval == 1.5


def test_ui_from_user_config(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_dir = tmp_path / ".config" / "aiosdeck"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "ui:\n  theme: desert\n  accent_intensity: 0.9\n  compact: true\n  refresh_interval: 3.0\n"
    )
    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()
    assert config.ui.theme == "desert"
    assert config.ui.accent_intensity == 0.9
    assert config.ui.compact is True
    assert config.ui.refresh_interval == 3.0


def test_detection_fallback(tmp_path):
    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()
    assert config.project.name == tmp_path.name


def test_quality_policy_from_user_config(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config_dir = tmp_path / ".config" / "aiosdeck"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(
        "quality:\n"
        "  environment: release\n"
        "  policy:\n"
        "    release: [critical, high, medium]\n"
        "  overrides:\n"
        "    - gate: code_gate\n"
        "      environment: dev\n"
        "      reason: accepted\n"
    )
    loader = ConfigLoader(project_path=tmp_path)
    config = loader.load()
    assert config.quality.environment == "release"
    assert config.quality.policy == {"release": ["critical", "high", "medium"]}
    assert config.quality.overrides == [
        {"gate": "code_gate", "environment": "dev", "reason": "accepted"}
    ]
