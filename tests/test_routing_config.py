"""Tests for routing config schema and loader."""

import os
import tempfile
from pathlib import Path

from aios.config.loader import ConfigLoader
from aios.config.schema import RouteConfig


class TestRouteConfig:
    def test_defaults(self):
        cfg = RouteConfig()
        assert cfg.enabled is True
        assert cfg.default_provider == "ollama"
        assert cfg.default_model == "llama3"
        assert cfg.default_variant == ""
        assert cfg.rules == []
        assert cfg.cost_cap == 0.0
        assert cfg.context_limits == {}
        assert cfg.fallback_providers == []

    def test_custom(self):
        cfg = RouteConfig(
            enabled=False,
            default_provider="anthropic",
            default_model="claude-sonnet",
            cost_cap=5.0,
            context_limits={"planner": 8000, "developer": 16000},
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-opus",
                },
            ],
            fallback_providers=[
                {"provider": "ollama", "model": "llama3"},
            ],
        )
        assert cfg.enabled is False
        assert cfg.default_provider == "anthropic"
        assert cfg.context_limits["planner"] == 8000
        assert cfg.cost_cap == 5.0
        assert len(cfg.rules) == 1
        assert len(cfg.fallback_providers) == 1


class TestConfigLoaderRouting:
    def test_env_routing_enabled(self):
        old = os.environ.get("AIOS_ROUTING_ENABLED")
        try:
            os.environ["AIOS_ROUTING_ENABLED"] = "0"
            loader = ConfigLoader()
            config = loader.load()
            assert config.routing.enabled is False
            assert config._sources["routing.enabled"] == "env:AIOS_ROUTING_ENABLED"
        finally:
            if old is not None:
                os.environ["AIOS_ROUTING_ENABLED"] = old
            else:
                os.environ.pop("AIOS_ROUTING_ENABLED", None)

    def test_env_routing_cost_cap(self):
        old = os.environ.get("AIOS_ROUTING_COST_CAP")
        try:
            os.environ["AIOS_ROUTING_COST_CAP"] = "10.5"
            loader = ConfigLoader()
            config = loader.load()
            assert config.routing.cost_cap == 10.5
        finally:
            if old is not None:
                os.environ["AIOS_ROUTING_COST_CAP"] = old
            else:
                os.environ.pop("AIOS_ROUTING_COST_CAP", None)

    def test_yaml_routing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".config" / "aiosdeck"
            home.mkdir(parents=True)
            yaml_content = """\
routing:
  enabled: false
  default_provider: anthropic
  default_model: claude-sonnet
  cost_cap: 3.0
  context_limits:
    planner: 8000
    developer: 16000
  rules:
    - agent: planner
      complexity: high
      provider: anthropic
      model: claude-opus
  fallback_providers:
    - provider: ollama
      model: llama3
"""
            (home / "config.yaml").write_text(yaml_content)

            loader = ConfigLoader(project_path=Path(tmp))
            loader._apply_user_config = lambda config: _apply_test_user_config(
                config, home / "config.yaml"
            )
            config = loader.load()

            assert config.routing.enabled is False
            assert config.routing.default_provider == "anthropic"
            assert config.routing.default_model == "claude-sonnet"
            assert config.routing.cost_cap == 3.0
            assert config.routing.context_limits == {"planner": 8000, "developer": 16000}
            assert len(config.routing.rules) == 1
            assert config.routing.rules[0]["agent"] == "planner"
            assert config.routing.rules[0]["complexity"] == "high"
            assert len(config.routing.fallback_providers) == 1
            assert config.routing.fallback_providers[0]["provider"] == "ollama"


def _apply_test_user_config(config, config_path):
    from aios.config.loader import ConfigLoader as CL

    loader = CL.__new__(CL)
    loader._sources = {}
    data = loader._load_yaml(config_path)
    if data is None:
        return config
    mapping = {
        "routing": {
            "enabled": "routing.enabled",
            "default_provider": "routing.default_provider",
            "default_model": "routing.default_model",
            "default_variant": "routing.default_variant",
            "rules": "routing.rules",
            "cost_cap": "routing.cost_cap",
            "context_limits": "routing.context_limits",
            "fallback_providers": "routing.fallback_providers",
        },
        "project": {"name": "project.name", "directory": "project.directory"},
    }
    loader._apply_mapped(data, config, mapping, str(config_path))
    return config
