# Plugin System

**Status**: Proposed
**Date**: 2026-08-02

## Context

AiosDeck ships with core components: OpenCode runtime, built-in agents, standard quality gates. But the ecosystem should be extensible. A developer using AiosDeck with a Spring Boot project should be able to install a Spring Boot plugin that adds specialized agents, quality gates, and skills. A DevOps team should be able to write a custom runtime adapter for their internal LLM proxy.

The Plugin System makes this possible. It defines **extension points** — stable interfaces that external code can implement — and a **registry** for discovering and loading plugins.

## Decision

### Architecture

```
Plugin Loader
   │
   ├── Discovers plugins (filesystem, pip, future: marketplace)
   │
   └── Registers plugins with the appropriate extension point
          │
          ├── Runtime Plugins      → RuntimeAdapter protocol
          ├── Agent Plugins        → Agent protocol
          ├── Skill Plugins        → SKILL.md files
          ├── Workflow Plugins     → Workflow protocol
          ├── Quality Gate Plugins → QualityGate protocol
          └── Detector Plugins     → LanguageDetector protocol
```

### Extension Points

AiosDeck defines five extension points. Each is a Python protocol that plugins implement:

| Extension Point | Protocol | Example Plugin |
|----------------|----------|---------------|
| Runtime | `RuntimeAdapter` | OpenCode adapter, DirectLLM adapter |
| Agent | `Agent` | Coder, Reviewer, custom domain agent |
| Skill | `SKILL.md` + metadata | `spring-boot`, `react-patterns` |
| Workflow | `WorkflowDefinition` | `/feature`, `/release`, custom workflow |
| Quality Gate | `QualityGate` | Custom security scanner, custom linter |
| Detector | `LanguageDetector` | Spring Boot detector, Laravel detector |

### Plugin Manifest

Every plugin declares a manifest:

```yaml
# aios/plugins/my-plugin/plugin.yaml
name: spring-boot-plugin
version: 1.0.0
type: agent                    # runtime, agent, skill, workflow, quality, detector
author: "Developer Name"
description: "Adds Spring Boot development support"
entry_point: "spring_plugin.SpringBootPlugin"
dependencies:
  - python >= 3.12
  - aiosdeck >= 0.9
capabilities:
  - filesystem_read
  - internet
```

### Discovery

Plugins are discovered from three locations:

```
1. <project>/aios/plugins/          (project-specific plugins)
2. ~/.config/aiosdeck/plugins/      (user plugins)
3. pip install aiosdeck-plugin-*    (PyPI plugins, future)
```

The Plugin Loader scans these directories, reads `plugin.yaml` files, validates manifests, and registers valid plugins.

### Loading

```python
class PluginLoader:
    def discover(self) -> list[PluginManifest]:
        plugins = []
        for directory in self._plugin_directories():
            for manifest_path in Path(directory).glob("*/plugin.yaml"):
                manifest = self._load_manifest(manifest_path)
                if self._validate(manifest):
                    plugins.append(manifest)
        return plugins

    def register(self, manifest: PluginManifest) -> None:
        if manifest.type == "agent":
            self._registry.register_agent(manifest)
        elif manifest.type == "runtime":
            self._registry.register_runtime(manifest)
        elif manifest.type == "workflow":
            self._registry.register_workflow(manifest)
        # ...
```

### Registry

The Plugin Registry is a centralized lookup for all registered plugins:

```python
class PluginRegistry:
    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._runtimes: dict[str, RuntimeAdapter] = {}
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._quality_gates: dict[str, QualityGate] = {}
        self._detectors: dict[str, LanguageDetector] = {}

    def get_agent(self, name: str) -> Agent: ...
    def list_agents(self) -> list[str]: ...
    def register_agent(self, manifest: PluginManifest) -> None: ...

    # ... same for each extension point
```

### CLI Integration

```
aios plugin list                    # List all installed plugins
aios plugin install <name>          # Install a plugin (from git, pip, or path)
aios plugin uninstall <name>        # Remove a plugin
aios plugin enable <name>           # Enable a disabled plugin
aios plugin disable <name>          # Disable a plugin (keep installed)
```

### Lifecycle

```
1. Kernel starts
2. Plugin Loader discovers plugins
3. Plugin Loader validates manifests
4. Plugin Loader registers valid plugins with Registry
5. Engine initialization: engines query Registry for extensions
6. Agents, Runtimes, Workflows, etc. can use registered plugins
7. Session runs normally
8. Kernel shuts down
9. Plugins are unloaded (cleanup hooks called)
```

### Sandboxing

Plugins run within the same process as AiosDeck. They are subject to the same security policies as built-in components:

- Plugins loaded from project directories have project-scoped capabilities
- Plugins loaded from user directories have user-scoped capabilities
- A malicious plugin is constrained by the Capability Manager

## Consequences

### Positive

- **Extensibility**: The community can extend AiosDeck without modifying core code.
- **Isolation**: Extension points use protocols. Plugin internals are opaque.
- **Discoverability**: `aios plugin list` shows all available plugins with descriptions.
- **Progressive adoption**: Core ships minimal. Users add plugins as needed.

### Negative

- **Maintenance burden**: Plugin authors may not update their plugins. Stale plugins break.
- **Security risk**: A malicious plugin can access anything the process can access. Capability Manager is the only guard.
- **Version conflicts**: Plugin A requires `aiosdeck >= 0.9`. Plugin B requires `aiosdeck == 0.9.0`. Resolution is manual.

### Neutral

- Plugin installation is manual in v0.9. A marketplace with automatic dependency resolution is post-v1.0.
- Plugins are loaded at session start. Hot-reload (install/remove during session) is future work.

## Implementation Notes

- [ ] Implement `plugins/registry.py` — PluginRegistry with dict-based storage per extension point
- [ ] Implement `plugins/loader.py` — PluginLoader with directory scanning and manifest parsing
- [ ] Define plugin manifest schema (YAML with name, version, type, entry_point, dependencies)
- [ ] Implement `aios plugin list|install|uninstall|enable|disable` CLI commands
- [ ] Plugin manifest validation: required fields, version format, dependency compatibility
- [ ] Plugin loading: dynamic import of entry_point
- [ ] Protocol validation: loaded plugin must implement the correct protocol for its type
- [ ] Test: discover plugins from project and user directories
- [ ] Test: register agent plugin → Registry.get_agent(name) returns the plugin
- [ ] Test: invalid manifest → plugin skipped with warning
- [ ] Test: dependency conflict → plugin skipped with error message
