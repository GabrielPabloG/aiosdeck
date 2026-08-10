# Phase 06 — Integrations

**Status**: Implemented (ProjDesk, OpenCode, ai-jail, Ollama); Deferred (Docker, VS Code, GitHub)
**Level**: Implementation
**Review date**: 2026-08-10
**Date**: 2026-08-02
**Target Version**: v0.9–v1.0

## Context

AiosDeck does not exist in isolation. It is part of an ecosystem: ProjDesk prepares the workspace, OpenCode executes agents, ai-jail enforces security, Ollama provides local LLM inference, Docker provides containerized runtimes, VS Code is the developer's IDE, and GitHub hosts repositories and CI/CD.

Each integration is an **adapter** — a thin layer that translates between AiosDeck's internal protocols and the external system's interface. Adapters are swappable. If a system is not available, the adapter degrades gracefully.

## Decision

### Integration Architecture

| Adapter | Status | Implementation |
|---------|--------|----------------|
| ProjDesk | Implemented | `integrations/projdesk/` — `ProjDeskClient`, `ProjectNotFound`, `ProjectAmbiguous` |
| OpenCode | Implemented | `runtime/opencode.py` — agent execution, headless permission enforcement |
| ai-jail | Implemented | `runtime/opencode.py` — always invoked via `ai-jail opencode`; degrades with warning when absent |
| Ollama | Implemented | `retrieval/providers.py` — `OllamaEmbeddingProvider`; default in `config/schema.py` |
| Docker | Deferred (post-1.0) | context detection only (`context/packet.py`); no adapter |
| VS Code | Deferred (post-1.0) | no adapter |
| GitHub | Deferred (post-1.0) | no adapter |

```
AiosDeck Core
     │
     ├── ProjDesk Adapter    (reads .aios/project.yaml, workspace context)   ✓ Implemented
     ├── OpenCode Adapter    (runtime: agent execution, skill loading)       ✓ Implemented
     ├── ai-jail Adapter     (sandbox: process isolation, filesystem masking) ✓ Implemented
     ├── Ollama Adapter      (LLM: local model inference)                    ✓ Implemented
     ├── Docker Adapter      (containers: development services)              ✗ Deferred
     ├── VS Code Adapter     (IDE: editor integration)                       ✗ Deferred
     └── GitHub Adapter      (VCS: PRs, issues, CI/CD)                       ✗ Deferred
```

### Adapter Protocol

Every integration adapter implements:

```python
class IntegrationAdapter(Protocol):
    name: str
    version: str

    async def is_available(self) -> bool: ...  # Can the system be reached?
    async def initialize(self) -> None: ...  # Setup connection
    async def health_check(self) -> bool: ...  # Is the system healthy?
    async def shutdown(self) -> None: ...  # Tear down
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

- [x] Implement base adapter protocol in `integrations/__init__.py`
- [x] ProjDesk adapter: `integrations/projdesk/client.py` + `exceptions.py`
- [x] OpenCode runtime adapter: `runtime/opencode.py`
- [x] ai-jail enforcement in the runtime adapter
- [x] Ollama embedding provider: `retrieval/providers.py`
- [ ] Docker / VS Code / GitHub adapters — Deferred (post-1.0)
- [x] Graceful degradation: critical failures abort, non-critical log warning
- [x] Test: adapter missing → logged warning, system continues
- [x] Test: OpenCode missing → critical error, system exits
