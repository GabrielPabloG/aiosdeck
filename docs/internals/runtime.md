# Runtime Adapter

**Status**: Accepted
**Date**: 2026-08-04

## Context

AiosDeck agents execute through a runtime — the environment that communicates with a language model. The Runtime Adapter abstracts this environment behind a stable interface so that agents are decoupled from any specific runtime.

The principle is: **the runtime is replaceable**. OpenCode is the primary runtime today. Tomorrow it could be a different agent framework, a direct LLM API, or a custom execution environment. Agents should not need to change.

## Decision

### Architecture

```
Agent
   │
   ▼
AgentExecutor (v0.5+)
   │
   ▼
Runtime Adapter (interface)
   │
   ▼
OpenCode Adapter (implementation)
   │
   ├── Invokes: ai-jail opencode
   ├── Communicates: via OpenCode CLI/stdin/stdout
   └── Loads Skills: via OpenCode skill tool (maps AiosDeck Skills into the runtime-native mechanism)
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

The adapter detects whether ai-jail is installed. If it is missing, execution is disabled rather than falling back to an unsandboxed process.

```python
async def _resolve_runtime_command(self) -> list[str]:
    if self._is_installed("ai-jail"):
        return ["ai-jail", "opencode"]
    logging.warning("ai-jail not found. OpenCode execution is disabled.")
    return ["ai-jail", "opencode", "(not found)"]
```

### Skill Loading

The OpenCode adapter maps AiosDeck Skills into OpenCode's native skill system. Skills are loaded before each task:

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

### Headless Tool Permissions (v0.6.1)

The adapter enforces OpenCode tool permissions at the process boundary via the `OPENCODE_PERMISSION` environment variable. This prevents tools that require human interaction (e.g., `question`) from causing silent timeouts in headless mode.

Permissions are derived from the agent's capabilities:
- `question: deny` — always blocked (no human to answer)
- PlannerAgent (`filesystem_read` only): `edit: deny`, `bash: deny`
- DeveloperAgent (`filesystem_write`, `shell`): only `question: deny`

Permissions are cached by capabilities set in `runtime/opencode.py` via `_build_permissions()`.

### Runtime Agent Selection

Write-capable executions — granted access includes `filesystem_write` or
`shell` (coarse capabilities or resolved granular actions) — pass
`--agent build`, so the OpenCode session is write-capable by construction. A
plan-only session could answer with text and never edit a file. Read-only
executions and bare probes keep the default agent (no flag); tool policy
remains enforced by `OPENCODE_PERMISSION` on the same invocation.

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
- **Explicit failure**: Refuses to run without ai-jail instead of weakening the security boundary.

### Negative

- **Latency**: Invoking OpenCode through ai-jail adds process startup overhead.
- **Single runtime**: v0.1 supports only one runtime at a time. Parallel runtimes are a future concern.
- **Prompt construction**: The adapter is responsible for building prompts. Any context not passed is lost.

### Neutral

- The adapter does not manage OpenCode installation or configuration. That is the user's responsibility.
- Skill discovery is delegated to OpenCode. The adapter only passes skill names.

## Implementation Notes

- [x] Implement `runtime/base.py` — RuntimeAdapter protocol
- [x] Implement `runtime/opencode.py` — OpenCodeAdapter implementation
- [x] `_resolve_runtime_command()` must detect ai-jail and return correct command
- [x] Prompt construction must inject context from Context Packet
- [x] Deep doctor diagnostic verifies OpenCode and ai-jail availability
- [x] Adapter must log every invocation with timestamp and result for the Audit Trail
- [x] Test: OpenCodeAdapter.execute() returns a Result
- [x] Test: adapter detects missing ai-jail and refuses unsandboxed execution
- [x] Test: health check returns True when OpenCode is installed
- [x] Test: prompt includes task description, context, and instructions
- [x] Inject OPENCODE_PERMISSION with per-agent tool lockdown (v0.6.1)
- [x] Select the write-capable build agent for write/shell-capable executions
