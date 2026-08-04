# Configuration

**Status**: Accepted
**Date**: 2026-08-04

## Context

AiosDeck must detect what it can and configure what it must. The philosophy is: **automation over prompts**. Configuration files exist only for what cannot be detected from the project or the environment.

This means the configuration system has a clear priority: **detection > project manifest > user config > environment variables > defaults**. Every value has a source, and that source is logged.

## Decision

### Configuration Sources (Priority Order)

```
1. Detection (Context Engine)       → highest priority, per-session
2. Project Manifest (.aios/project.yaml) → project-specific overrides
3. User Config (~/.config/aiosdeck/config.yaml) → personal preferences
4. Environment Variables (AIOS_*)   → deployment overrides
5. Built-in Defaults                → lowest priority, always present
```

### Configuration Schema

```python
@dataclass
class AiosDeckConfig:
    # Runtime
    runtime_adapter: str = "opencode"
    sandbox: str = "ai-jail"
    runtime_command: str = "ai-jail opencode"

    # LLM
    default_model: str = "ollama"        # ollama, openai, anthropic, google
    ollama_model: str = "llama3"
    ollama_host: str = "http://localhost:11434"

    # Memory
    memory_enabled: bool = True
    memory_path: str = "~/.local/share/aiosdeck/memory.db"

    # Security
    security_enabled: bool = True
    policies_dir: str = "aios/policies"

    # Quality
    quality_enabled: bool = True
    quality_auto_detect: bool = True

    # Logging
    log_level: str = "INFO"
    audit_log_path: str = "~/.local/share/aiosdeck/audit.log"

    # Project
    projects_dir: str = "~/projects"

    # Session
    auto_context: bool = True
    auto_memory_restore: bool = True
    skills_auto_load: bool = True
```

### Environment Variables

All environment variables use the `AIOS_` prefix and are uppercase with underscores:

| Variable | Config Field | Example |
|----------|-------------|---------|
| `AIOS_RUNTIME_ADAPTER` | `runtime_adapter` | `opencode` |
| `AIOS_SANDBOX` | `sandbox` | `ai-jail` |
| `AIOS_DEFAULT_MODEL` | `default_model` | `ollama` |
| `AIOS_OLLAMA_MODEL` | `ollama_model` | `llama3` |
| `AIOS_MEMORY_ENABLED` | `memory_enabled` | `true` |
| `AIOS_LOG_LEVEL` | `log_level` | `DEBUG` |
| `AIOS_PROJECTS_DIR` | `projects_dir` | `~/projects` |
| `AIOS_OPENCODE_PERMISSION` | OpenCode tool permissions (injected by Runtime Adapter) | `{"question": "deny"}` |

### Project Manifest

```yaml
# .aios/project.yaml
name: my-project
language: python
runtime: opencode
sandbox: ai-jail

quality:
  lint: ruff
  format: black
  tests: pytest

skills:
  - project-dna
  - coding-style

workflows:
  - feature
  - fix
  - review
```

### User Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
runtime:
  adapter: opencode
  command: "ai-jail opencode --verbose"

memory:
  enabled: true
  path: "~/.local/share/aiosdeck/memory.db"

security:
  enabled: true
  policies_dir: "aios/policies"

logging:
  level: "DEBUG"
```

### Configuration Loading Algorithm

```python
class ConfigLoader:
    def load(self, project_path: str) -> AiosDeckConfig:
        config = self._load_defaults()           # Step 1: defaults
        config = self._apply_env(config)          # Step 2: env vars
        config = self._apply_user_config(config)  # Step 3: user file
        config = self._apply_project_manifest(config, project_path)  # Step 4: manifest
        config = self._apply_detection(config, project_path)  # Step 5: detection
        self._validate(config)                    # Step 6: validate
        return config
```

Each `_apply_*` method only overrides fields that are explicitly set in that source. If a source does not define a value, the previously set value is preserved.

### Validation

```python
def _validate(self, config: AiosDeckConfig) -> None:
    if config.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"Invalid log level: {config.log_level}")
    if config.default_model not in ("ollama", "openai", "anthropic", "google"):
        raise ConfigError(f"Invalid model: {config.default_model}")
    # Validate paths exist or can be created
```

### Debugging

Every configuration load logs the source of each field:

```
[INFO] config.default_model = "ollama" (source: defaults)
[INFO] config.ollama_model = "llama3" (source: env AIOS_OLLAMA_MODEL)
[INFO] config.runtime_command = "ai-jail opencode --verbose" (source: user config)
```

## Consequences

### Positive

- **Predictable**: A developer can trace any value to its source.
- **Flexible**: Every value can be overridden at any level.
- **Discoverable**: `AIOS_*` environment variables are self-documenting.
- **Testable**: Each source is loaded independently and merged deterministically.

### Negative

- **Merge complexity**: Five overlapping sources can produce surprising results.
- **Debugging overhead**: The "where did this value come from?" problem requires logging.
- **Validation burden**: Each source must be validated independently before merging.

### Neutral

- Configuration is loaded once per session. Hot-reload is not supported in v0.1.
- The schema will grow as new components (Scheduler, Plugin System) are introduced.

## Implementation Notes

- [ ] Implement `config/schema.py` — AiosDeckConfig dataclass with default values
- [ ] Implement `config/loader.py` — ConfigLoader with 5-source merge
- [ ] Each `_apply_*` method must log which fields it changed and from which source
- [ ] Environment variables must be uppercase with AIOS_ prefix and use underscores
- [ ] Paths in config must support `~` expansion
- [ ] Validation must reject invalid values before configuration is used
- [ ] Test: defaults only → valid config with all default values
- [ ] Test: env overrides defaults → env value takes precedence
- [ ] Test: user config overrides both → user config wins
- [ ] Test: manifest overrides user config → manifest wins
- [ ] Test: detection overrides all → detection wins
- [ ] Test: invalid log_level → ConfigError raised
