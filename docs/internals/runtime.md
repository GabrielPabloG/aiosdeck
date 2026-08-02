# Runtime Adapter

**Status**: Draft
**Date**: 2026-08-02

## Context

AiosDeck agents execute through a runtime — the environment that communicates with a language model. The Runtime Adapter abstracts this environment behind a stable interface so that agents are decoupled from any specific runtime.

The principle is: **the runtime is replaceable**. OpenCode is the primary runtime today. Tomorrow it could be a different agent framework, a direct LLM API, or a custom execution environment. Agents should not need to change.

## Decision

### Architecture

```
Agent
   │
   ▼
Runtime Adapter (interface)
   │
   ▼
OpenCode Adapter (implementation)
   │
   ├── Invokes: ai-jail opencode
   ├── Communicates: via OpenCode CLI/stdin/stdout
   └── Loads Skills: via OpenCode skill tool
```

### Runtime Protocol

Every runtime adapter must implement:

```python
class RuntimeAdapter(Protocol):
    name: str
    version: str

    async def initialize(self) -> None: ...
    async def execute(self, task: Task, context: ContextPacket, skills: list[str]) -> Result: ...
    async def health_check(self) -> bool: ...
    async def shutdown(self) -> None: ...
```

### OpenCode Adapter

The OpenCode adapter is the first (and initially only) implementation:

```python
class OpenCodeAdapter:
    name = "opencode"
    version = "1.0"

    async def execute(self, task: Task, context: ContextPacket, skills: list[str]) -> Result:
        # 1. Build prompt from task + context
        prompt = self._build_prompt(task, context)

        # 2. Load required skills
        for skill in skills:
            await self._load_skill(skill)

        # 3. Execute via ai-jail
        result = await self._invoke_opencode(prompt)

        # 4. Parse and return result
        return self._parse_result(result)
```

### Invocation

OpenCode is **always** invoked through ai-jail. The adapter never calls `opencode` directly:

```bash
# Correct
ai-jail opencode <prompt>

# Never
opencode <prompt>
```

The adapter detects whether ai-jail is installed. If not, it logs a warning and falls back to direct invocation — but this is a degraded mode, not the intended path.

```python
async def _resolve_runtime_command(self) -> list[str]:
    if self._is_installed("ai-jail"):
        return ["ai-jail", "opencode"]
    logging.warning("ai-jail not found. Running OpenCode without sandbox.")
    return ["opencode"]
```

### Skill Loading

The adapter uses OpenCode's native skill system. Skills are loaded before each task:

```python
async def _load_skill(self, skill_name: str) -> None:
    # Skills are discovered by OpenCode. The adapter only
    # passes the skill name. OpenCode loads it from
    # .opencode/skills/<name>/SKILL.md or
    # ~/.config/opencode/skills/<name>/SKILL.md
    pass
```

The list of skills to load comes from the Project Manifest and the agent's `required_skills` configuration.

### Task → Prompt Transformation

The adapter converts a Task and Context into a prompt:

```python
def _build_prompt(self, task: Task, context: ContextPacket) -> str:
    return f"""
## Task
{task.description}

## Project Context
- Language: {context.tools.language}
- Framework: {context.tools.framework or "none"}
- Test runner: {context.tools.test_runner}
- Linter: {context.tools.linter}

## Git Status
- Branch: {context.git.branch}
- Status: {context.git.status}

## Instructions
{task.instructions or "Complete the task as described."}
"""
```

Future versions will support richer prompt construction (memory injection, code snippets, related file context). The v0.1 adapter is intentionally minimal.

### Health Check

```python
async def health_check(self) -> bool:
    if not self._is_installed("opencode"):
        return False
    if not self._is_installed("ai-jail"):
        logging.warning("ai-jail not found")
    return True
```

### Configuration

Runtime configuration is read from the Project Manifest:

```yaml
# .aios/project.yaml
runtime: opencode
sandbox: ai-jail
```

Or from user configuration:

```yaml
# ~/.config/aiosdeck/config.yaml
runtime:
  adapter: opencode
  sandbox: ai-jail
  command: "ai-jail opencode"  # custom command if needed
```

## Consequences

### Positive

- **Swappable**: Changing the runtime requires only a new adapter implementation.
- **Safe by default**: Always runs through ai-jail. Sandbox escape requires explicit configuration.
- **Minimal interface**: Three methods. Easy to implement for new runtimes.
- **Graceful degradation**: Works without ai-jail (with warning).

### Negative

- **Latency**: Invoking OpenCode through ai-jail adds process startup overhead.
- **Single runtime**: v0.1 supports only one runtime at a time. Parallel runtimes are a future concern.
- **Prompt construction**: The adapter is responsible for building prompts. Any context not passed is lost.

### Neutral

- The adapter does not manage OpenCode installation or configuration. That is the user's responsibility.
- Skill discovery is delegated to OpenCode. The adapter only passes skill names.

## Implementation Notes

- [ ] Implement `runtime/base.py` — RuntimeAdapter protocol
- [ ] Implement `runtime/opencode.py` — OpenCodeAdapter implementation
- [ ] `_resolve_runtime_command()` must detect ai-jail and return correct command
- [ ] Prompt construction must inject context from Context Packet
- [ ] Health check must verify both OpenCode and ai-jail availability
- [ ] Adapter must log every invocation with timestamp and result for the Audit Trail
- [ ] Test: OpenCodeAdapter.execute() returns a Result
- [ ] Test: adapter detects missing ai-jail and falls back with warning
- [ ] Test: health check returns True when OpenCode is installed
- [ ] Test: prompt includes task description, context, and instructions
