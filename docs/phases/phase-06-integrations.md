# Phase 06 — Integrations

**Status**: Proposed
**Date**: 2026-08-02
**Target Version**: v0.9–v1.0

## Context

AiosDeck does not exist in isolation. It is part of an ecosystem: ProjDesk prepares the workspace, OpenCode executes agents, ai-jail enforces security, Ollama provides local LLM inference, Docker provides containerized runtimes, VS Code is the developer's IDE, and GitHub hosts repositories and CI/CD.

Each integration is an **adapter** — a thin layer that translates between AiosDeck's internal protocols and the external system's interface. Adapters are swappable. If a system is not available, the adapter degrades gracefully.

## Decision

### Integration Architecture

```
AiosDeck Core
     │
     ├── ProjDesk Adapter    (reads .aios/project.yaml, workspace context)
     ├── OpenCode Adapter    (runtime: agent execution, skill loading)
     ├── ai-jail Adapter     (sandbox: process isolation, filesystem masking)
     ├── Ollama Adapter      (LLM: local model inference)
     ├── Docker Adapter      (containers: development services)
     ├── VS Code Adapter     (IDE: editor integration)
     └── GitHub Adapter      (VCS: PRs, issues, CI/CD)
```

### Adapter Protocol

Every integration adapter implements:

```python
class IntegrationAdapter(Protocol):
    name: str
    version: str

    async def is_available(self) -> bool: ...        # Can the system be reached?
    async def initialize(self) -> None: ...            # Setup connection
    async def health_check(self) -> bool: ...          # Is the system healthy?
    async def shutdown(self) -> None: ...              # Tear down
```

### Discovery

Adapters detect availability automatically:

```python
class ProjDeskAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("pd") or self._is_installed("projdesk")

class OpenCodeAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("opencode")

class AiJailAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("ai-jail")

class OllamaAdapter:
    async def is_available(self) -> bool:
        try:
            response = await self._http_get("http://localhost:11434/api/tags")
            return response.status == 200
        except Exception:
            return False

class DockerAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("docker") and self._run("docker info").returncode == 0

class VSCodeAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("code")

class GitHubAdapter:
    async def is_available(self) -> bool:
        return self._has_env("GITHUB_TOKEN") or self._run("gh auth status").returncode == 0
```

### Graceful Degradation

If an integration is unavailable, the system continues without it:

| Adapter Missing | Impact |
|----------------|--------|
| ProjDesk | No workspace automation. Project path must be specified manually. |
| OpenCode | **Critical**. Cannot execute agents. |
| ai-jail | Agents run without sandbox. Warning logged. |
| Ollama | Cloud LLM fallback (if configured). Otherwise, **critical**. |
| Docker | No containerized services. Development services run manually. |
| VS Code | No IDE integration. File changes are filesystem-only. |
| GitHub | No PR/issue automation. Git operations still work locally. |

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `session.start` | Consumed | Initialize all adapters |
| `runtime.ready` | Emitted | Runtime integration available (OpenCode + ai-jail) |
| `runtime.error` | Emitted | Runtime integration failed |
| `session.shutdown` | Consumed | Shutdown all adapters |

### Integration Testing

Each adapter is tested in isolation:

1. `is_available()` returns the correct boolean
2. `initialize()` succeeds when the system is installed
3. `health_check()` reflects actual system health
4. `shutdown()` cleans up resources
5. Missing system → graceful degradation, not crash

## Consequences

### Positive

- **Loose coupling**: Core system does not depend on any specific integration.
- **Auto-detection**: No configuration needed. Adaptors detect their own availability.
- **Graceful degradation**: Missing tools do not crash the system.
- **Testability**: Each adapter can be tested independently with mock external systems.

### Negative

- **Adapter maintenance**: Each integration requires ongoing maintenance as external APIs evolve.
- **Startup latency**: Each adapter's health check runs at session start.
- **Implicit dependencies**: OpenCode is effectively required, but the protocol allows swapping.

### Neutral

- Integration adapters are thin. Most logic lives in the core system.
- Each integration has its own detailed ADR in `integrations/*.md`.

## Implementation Notes

- [ ] Implement base adapter protocol in `integrations/__init__.py`
- [ ] Discovery loop: check all adapters at session start, log availability
- [ ] Graceful degradation: critical failures abort, non-critical log warning
- [ ] Test: all adapters installed → all available
- [ ] Test: adapter missing → logged warning, system continues
- [ ] Test: OpenCode missing → critical error, system exits
