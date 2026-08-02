# Docker Integration

**Status**: Draft
**Date**: 2026-08-02

## Context

Many projects use Docker for development services (databases, caches, queues) and for containerized runtimes. AiosDeck detects Docker availability and Compose configuration — it does not manage Docker containers directly, but it uses Docker for:
1. Running ai-jail in a containerized sandbox (future)
2. Starting project services before agent execution (future)
3. Reporting Docker status in the dashboard

The principle is: **detect, do not ask**. If a `docker-compose.yml` exists, AiosDeck knows Docker is relevant to the project.

## Decision

### Detection

```python
class DockerAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("docker") and self._run("docker info").returncode == 0

    async def detect_compose(self, project_path: str) -> list[str]:
        compose_files = []
        for pattern in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
            path = Path(project_path) / pattern
            if path.exists():
                compose_files.append(str(path))
        return compose_files

    async def is_running(self, compose_file: str) -> bool:
        result = await self._run(f"docker compose -f {compose_file} ps --status running")
        return result.returncode == 0

    async def health_check(self) -> bool:
        return await self.is_available()
```

### Context Integration

Docker information is added to the Context Packet:

```python
context["docker"] = {
    "installed": True,
    "running": True,
    "compose_files": ["docker-compose.yml"],
    "compose_dev_overrides": ["docker-compose.dev.yml"],  # if exists
}
```

### Status Dashboard

```
──────────────────────────────
 ProjDesk
 Workspace Ready
──────────────────────────────
 Docker        Running        ← AiosDeck reports Docker status
 Git           main
 ...
```

### Future Integration (v1.0+)

- Automatic `docker compose up` when entering a project (configurable)
- Containerized ai-jail runtime (Docker sandbox for agents)
- Docker health monitoring: restart failed containers
- Multi-service orchestration for microservice projects

## Consequences

- **Detection only**: v0.1 detects Docker. Future versions manage it.
- **Graceful degradation**: Missing Docker is not an error. Services run manually.
- **Integration scope**: Docker is an environment provider, not an AiosDeck dependency.

## Implementation Notes

- [ ] Docker adapter: detect docker binary and running daemon
- [ ] Compose detection: scan for `docker-compose.yml` and variants
- [ ] Context enrichment: add docker status to Context Packet
- [ ] Dashboard display: show Docker status in session output
- [ ] Test: Docker installed and running → adapter reports available
- [ ] Test: Docker not installed → adapter reports unavailable, system continues
- [ ] Test: compose file detected → added to context
