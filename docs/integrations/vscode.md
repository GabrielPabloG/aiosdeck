# VS Code Integration

**Status**: Accepted
**Date**: 2026-08-02

## Context

VS Code is the default IDE for ProjDesk. AiosDeck integrates with VS Code for: opening files edited by agents directly in the editor, displaying review results inline, and providing a status bar integration.

The VS Code integration is secondary to the CLI. AiosDeck is primarily a CLI tool. VS Code integration is a convenience, not a requirement.

## Decision

### Detection

```python
class VSCodeAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("code") or self._is_installed("code-insiders")

    async def open_file(self, file_path: str, line: int = 1) -> None:
        await self._run(f"code --goto {file_path}:{line}")

    async def open_project(self, project_path: str) -> None:
        await self._run(f"code {project_path}")

    async def health_check(self) -> bool:
        return await self.is_available()
```

### Context Integration

```python
context["editor"] = {
    "name": "vscode",
    "installed": True,
}
```

### Future Integration (v1.0+)

- **AiosDeck VS Code Extension**: Sidebar showing agent status, workflow progress, review findings
- **Inline reviews**: Reviewer findings displayed as VS Code diagnostic messages
- **Agent chat panel**: Chat interface for interacting with agents directly from the editor
- **Status bar item**: Show current agent activity in VS Code status bar

### Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
editor:
  name: vscode
  command: code
```

## Consequences

- **Optional**: VS Code integration is a convenience. CLI is the primary interface.
- **Single IDE**: v0.1 supports only VS Code. Plugin system (v0.9) enables other editors.
- **Detection based**: No configuration required. VS Code is detected if installed.

## Implementation Notes

- [ ] VS Code adapter: detect `code` or `code-insiders` in PATH
- [ ] File opening: use `code --goto` for line-specific navigation
- [ ] Context enrichment: add editor info to Context Packet
- [ ] Test: VS Code installed → adapter reports available
- [ ] Test: VS Code not installed → adapter reports unavailable
