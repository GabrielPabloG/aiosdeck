# ai-jail Integration

**Status**: Draft
**Date**: 2026-08-02

## Context

ai-jail provides sandboxed execution for AI agents. It isolates processes, masks secrets, restricts filesystem access, and enforces per-project policies. The Security Manager in AiosDeck provides application-level authorization (capabilities, policies, audit). ai-jail provides OS-level isolation. Together they form defense-in-depth.

## Decision

### Invocation

The Runtime Adapter always invokes OpenCode through ai-jail:

```bash
ai-jail opencode
```

If ai-jail is not installed, the adapter logs a warning and invokes OpenCode directly:

```python
async def _resolve_runtime_command(self) -> list[str]:
    if self._is_installed("ai-jail"):
        return ["ai-jail", "opencode"]
    logging.warning("ai-jail not found. Running OpenCode without sandbox.")
    return ["opencode"]
```

### Sandbox Capabilities

ai-jail provides:
- **Process isolation**: Agent code runs in a separate process
- **Filesystem masking**: Only allowed directories are visible
- **Secret masking**: Environment secrets are hidden from the agent
- **Policy enforcement**: Per-project policies define what is allowed
- **Resource limits**: CPU, memory, and time limits per agent run

### Policy Alignment

AiosDeck policies (capabilities) and ai-jail policies (filesystem masks, resource limits) are complementary:

| Layer | Responsibility |
|-------|---------------|
| AiosDeck Security Manager | Agent-level: can this agent write files? |
| ai-jail | OS-level: which directories can this process see? |

They do not overlap. AiosDeck decides **what** an agent can do. ai-jail decides **where** and **how much**.

### Configuration

```yaml
# .aios/project.yaml
sandbox: ai-jail

# ~/.config/aiosdeck/config.yaml
runtime:
  command: "ai-jail opencode"
```

### Health Check

```python
class AiJailAdapter:
    async def is_available(self) -> bool:
        return self._is_installed("ai-jail")

    async def health_check(self) -> bool:
        result = await self._run("ai-jail --version")
        return result.returncode == 0
```

### Degraded Mode

Without ai-jail, agents run directly. The Security Manager still enforces capability checks, but there is no OS-level isolation. This is acceptable for:
- Development (trusted code on a developer's machine)
- Environments where ai-jail is being installed

For production or untrusted code, ai-jail is required.

## Consequences

- **Defense in depth**: AiosDeck + ai-jail = application + OS security layers
- **Transparent to agents**: Agents are unaware of ai-jail. The Runtime Adapter handles it.
- **Optional but recommended**: System functions without ai-jail, but with reduced security.

## Implementation Notes

- [ ] Runtime Adapter must detect ai-jail: `which ai-jail`
- [ ] Runtime command resolution: ai-jail present → `ai-jail opencode`, absent → `opencode`
- [ ] Health check: verify ai-jail responds to `--version`
- [ ] Warning log: "ai-jail not found. Running without sandbox."
- [ ] Policy file location: ai-jail reads policies from its own config directory
- [ ] Test: ai-jail installed → command is `ai-jail opencode`
- [ ] Test: ai-jail not installed → warning logged, fallback to direct OpenCode
- [ ] Test: ai-jail healthy → health check returns True
