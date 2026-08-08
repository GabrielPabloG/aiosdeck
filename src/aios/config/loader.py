"""Configuration loader — 5-source merge with source tracking."""

import logging
import os
from pathlib import Path
from typing import Any

from aios.config.schema import AiosDeckConfig

logger = logging.getLogger("aios.config")

YAML_AVAILABLE = False
try:
    import yaml  # type: ignore

    YAML_AVAILABLE = True
except ImportError:
    pass


class ConfigLoader:
    def __init__(self, project_path: Path | None = None) -> None:
        self.project_path = project_path or Path.cwd()
        self._sources: dict[str, str] = {}

    def load(self) -> AiosDeckConfig:
        config = AiosDeckConfig()
        config = self._apply_env(config)
        config = self._apply_user_config(config)
        config = self._apply_project_manifest(config)
        config = self._apply_detection(config)
        config._sources = dict(self._sources)
        return config

    def _set_field(self, obj: object, field_path: str, value: Any, source: str) -> None:
        parts = field_path.split(".")
        target = obj
        for part in parts[:-1]:
            target = getattr(target, part)
        field_name = parts[-1]
        if hasattr(target, field_name):
            setattr(target, field_name, value)
            self._sources[field_path] = source

    def _apply_env(self, config: AiosDeckConfig) -> AiosDeckConfig:
        env_map = {
            "AIOS_RUNTIME_ADAPTER": "runtime.adapter",
            "AIOS_SANDBOX": "runtime.sandbox",
            "AIOS_RUNTIME_COMMAND": "runtime.command",
            "AIOS_DEFAULT_MODEL": "model.default",
            "AIOS_OLLAMA_MODEL": "model.ollama_model",
            "AIOS_OLLAMA_HOST": "model.ollama_host",
            "AIOS_MEMORY_ENABLED": "memory.enabled",
            "AIOS_MEMORY_PATH": "memory.path",
            "AIOS_SECURITY_ENABLED": "security.enabled",
            "AIOS_LOG_LEVEL": "logging.level",
            "AIOS_AUDIT_PATH": "logging.audit_path",
            "AIOS_LEARNING_ENABLED": "learning.enabled",
            "AIOS_PROJECT_NAME": "project.name",
            "AIOS_PROJECTS_DIR": "project.directory",
            "AIOS_ROUTING_ENABLED": "routing.enabled",
            "AIOS_ROUTING_COST_CAP": "routing.cost_cap",
        }
        for env_var, field_path in env_map.items():
            value = os.environ.get(env_var)
            if value is not None:
                coerced = self._coerce(value, field_path)
                self._set_field(config, field_path, coerced, f"env:{env_var}")
        return config

    def _apply_user_config(self, config: AiosDeckConfig) -> AiosDeckConfig:
        config_path = Path.home() / ".config" / "aiosdeck" / "config.yaml"
        if not config_path.exists():
            return config

        data = self._load_yaml(config_path)
        if data is None:
            return config

        user_map = {
            "runtime": {
                "adapter": "runtime.adapter",
                "sandbox": "runtime.sandbox",
                "command": "runtime.command",
            },
            "model": {
                "default": "model.default",
                "ollama_model": "model.ollama_model",
                "ollama_host": "model.ollama_host",
            },
            "memory": {"enabled": "memory.enabled", "path": "memory.path"},
            "security": {
                "enabled": "security.enabled",
                "policies_dir": "security.policies_dir",
            },
            "quality": {
                "enabled": "quality.enabled",
                "auto_detect": "quality.auto_detect",
                "environment": "quality.environment",
                "policy": "quality.policy",
                "overrides": "quality.overrides",
            },
            "logging": {"level": "logging.level", "audit_path": "logging.audit_path"},
            "learning": {
                "enabled": "learning.enabled",
                "auto_capture": "learning.auto_capture",
                "confidence_threshold": "learning.confidence_threshold",
                "min_evidence": "learning.min_evidence",
                "recurrence_threshold": "learning.recurrence_threshold",
                "policy": "learning.policy",
            },
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
        source = str(config_path)
        self._apply_mapped(data, config, user_map, source)
        return config

    def _apply_project_manifest(self, config: AiosDeckConfig) -> AiosDeckConfig:
        manifest_path = self.project_path / ".aios" / "project.yaml"
        if not manifest_path.exists():
            return config

        data = self._load_yaml(manifest_path)
        if data is None:
            return config

        source = str(manifest_path)
        manifest_mapping = {
            "name": "project.name",
            "runtime": "runtime.adapter",
            "sandbox": "runtime.sandbox",
        }
        for key, field_path in manifest_mapping.items():
            value = data.get(key)
            if value is not None:
                self._set_field(config, field_path, value, source)

        skills = data.get("skills")
        if isinstance(skills, list):
            config.project.skills = skills
            self._sources["project.skills"] = source

        return config

    def _apply_detection(self, config: AiosDeckConfig) -> AiosDeckConfig:
        if not config.project.name:
            config.project.name = self.project_path.name
            self._sources["project.name"] = "detection"

        return config

    def _apply_mapped(self, data: dict, config: AiosDeckConfig, mapping: dict, source: str) -> None:
        for top_key, field_mapping in mapping.items():
            section = data.get(top_key)
            if not isinstance(section, dict):
                continue
            for yaml_key, field_path in field_mapping.items():
                value = section.get(yaml_key)
                if value is not None:
                    self._set_field(config, field_path, value, source)

    def _load_yaml(self, path: Path) -> dict | None:
        if not YAML_AVAILABLE:
            logger.debug("PyYAML not installed, skipping %s", path)
            return None
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except (OSError, ImportError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return None

    @staticmethod
    def _coerce(value: str, field_path: str) -> Any:
        if field_path.endswith(".enabled"):
            return value.lower() in ("true", "1", "yes")
        if field_path.endswith(".cost_cap"):
            return float(value)
        return value
