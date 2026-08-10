# Phase 01 — Kernel

**Status**: Implemented
**Level**: Architecture
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Target Version**: v0.1

## Context

The Kernel is the central coordinator of the AiosDeck system. It bootstraps all engines, manages the system lifecycle, and dispatches events between components. Without a Kernel, there is no AiosDeck — every other component depends on it to initialize and communicate.

The Kernel must be small, predictable, and testable. It should do nothing more than what is strictly required to bring the system to a running state. All domain logic lives in engines, not in the Kernel.

## Decision

### Architecture

The Kernel follows an **initializer-then-dispatch** pattern:

```
1. CLI parses command (aios start, aios exit)
2. Kernel receives parsed command
3. Kernel initializes subsystems in dependency order
4. Kernel emits session.start event
5. System enters listening state
6. Components communicate via Event Bus
7. Kernel emits session.shutdown on exit
8. Kernel terminates subsystems in reverse order
```

### Initialization Order

Engines are initialized in dependency order. If an engine fails to initialize, the Kernel logs the error and either continues (graceful degradation) or aborts (critical failure).

```
1. Configuration      (loads config from files, env, defaults)
2. Event Bus          (starts dispatcher, registers topics)
3. Security Manager   (loads policies, starts audit logger)
4. Context Engine     (detects project characteristics)
5. Memory Engine      (connects to SQLite, restores prior state)
6. Runtime Adapter    (spawns OpenCode via ai-jail)
7. Kernel emits session.ready
```

### Entry Point Contract

The CLI (`aios`) uses a Command Registry pattern (v0.6.1) instead of hardcoded if/elif chains. Commands are registered in `cli/commands.py` as `COMMANDS = { ... }` with name, description, aliases, and execute callable. The thin dispatcher in `cli/main.py` resolves command names or aliases and delegates execution.

| Command | Description | Event Emitted |
|---------|-------------|---------------|
| `aios` (no args) | Show dashboard | `session.start` |
| `aios doctor` | Run diagnostics | `session.start` |
| `aios plan <intent>` | Decompose goal into subtasks | `session.start` |
| `aios memory <cmd>` | Manage project knowledge | `session.start`, `memory.*` |
| `aios help` | Show help | (none) |
| `aios exit` | Shut down gracefully (hidden) | `session.shutdown` |
| `aios dashboard` | Show dashboard (primary, aliases: start, status) | `session.start` |

Note: `aios` without arguments is the primary entry point. `start`, `status`, and `exit` remain as hidden aliases. `__complete` is a hidden command for shell autocomplete. All commands derive from the single `COMMANDS` registry.

### Subsystem Contract

Every subsystem (engine) must implement:

```python
class Engine(Protocol):
    name: str

    async def initialize(self, bus: EventBus) -> None: ...
    async def shutdown(self) -> None: ...
    async def health_check(self) -> bool: ...
```

The Kernel iterates over registered engines at startup and shutdown. Engines register themselves via a decorator or registration function.

### Public API (`aios` CLI)

```bash
aios                    # Show dashboard (primary entry point)
aios doctor             # Run diagnostics
aios memory <cmd>       # Manage project knowledge
aios help               # Show help
aios --help             # Show help (alias)
aios --version          # Show version
```

### Configuration Flow

```
1. Kernel loads default configuration
2. Kernel loads project manifest (.aios/project.yaml) if present
3. Kernel loads user configuration (~/.config/aiosdeck/config.yaml) if present
4. Kernel loads environment variables (AIOS_* prefixed)
5. Merged configuration is passed to each engine on initialization
```

Configuration is documented in [internals/configuration.md](../internals/configuration.md).

### Error Handling

| Error | Severity | Behavior |
|-------|----------|----------|
| Config file parse error | Warning | Use defaults, log warning |
| Event Bus init failure | Critical | Abort |
| Security Manager init failure | Critical | Abort |
| Context detection failure | Warning | Proceed without context, log warning |
| Memory Engine init failure | Warning | Proceed without memory, log warning |
| Runtime Adapter failure | Warning | Proceed with warning. Re-attempt on first agent task. |
| ai-jail not found | Warning | Log warning. Suggest installation. OpenCode invoked directly with warning. |

## Consequences

### Positive

- **Simplicity**: The Kernel is ~100 lines. All complexity is delegated to engines.
- **Testability**: Each engine can be tested in isolation by mocking the Event Bus.
- **Graceful degradation**: Non-critical engine failures do not prevent session start.
- **Observability**: Every lifecycle event is emitted, enabling monitoring and debugging.

### Negative

- **Sequential initialization**: Engines start one by one. Fast engines wait for slow ones.
- **Tight coupling at startup**: All engines must implement the same protocol. A misbehaving engine blocks startup.
- **Command pass-through**: The Kernel knows about workflow commands but does not validate them. Validation happens in the Workflow Engine.

### Neutral

- The Kernel does not manage threads, processes, or concurrency. That responsibility belongs to the Scheduler (v0.8).
- The Kernel is intentionally anemic. It should never grow beyond initialization and shutdown coordination.

## Implementation Notes

- [x] Implement `core/kernel.py` — Engine protocol, registration, lifecycle management
- [x] Implement `cli/main.py` — Thin dispatcher consuming Command Registry (v0.6.1)
- [x] Implement `cli/commands.py` — Command dataclass + COMMANDS registry (v0.6.1)
- [x] Implement `core/__init__.py` — Package initialization
- [x] Implement `__main__.py` — `python -m aiosdeck` entry point
- [x] Kernel must validate that ai-jail and OpenCode are installed before proceeding
- [x] `aios` dashboard renders the status overview shown in the README
- [x] `aios doctor --json` must output machine-readable status for scripting
- [x] Config merge order must be verified with tests: defaults < manifest < user config < env
- [x] Graceful degradation tests: start with missing ai-jail, missing Docker, etc.
- [ ] Event: emit `session.start` on initialization, `session.ready` when all engines are up, `session.shutdown` on exit — topics registered in `events/events.py`, but emission is not implemented (post-1.0)
