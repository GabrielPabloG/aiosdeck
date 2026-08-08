# OpenCode Integration

**Status**: Accepted
**Date**: 2026-08-04

## Context

OpenCode is the active agent runtime for AiosDeck today (see ADR-0001). It provides: a CLI interface for agent interaction, a native skill system for loading reusable knowledge, tool execution (file operations, shell commands), and model provider abstraction (Ollama, OpenAI, Anthropic, Google).

AiosDeck does not compete with OpenCode. It extends it. OpenCode is the execution engine; AiosDeck is the orchestration layer above it. The Runtime Is Replaceable: when a different runtime becomes active, only the adapter changes.

## Decision

### Invocation

OpenCode is **always** invoked through ai-jail:

```bash
ai-jail opencode
```

Never directly:

```bash
opencode  # Not allowed
```

The Runtime Adapter (`runtime/opencode.py`) handles this. If ai-jail is not installed, a warning is logged and OpenCode is invoked directly — but this is degraded mode, not the intended path.

### Skill Loading

When OpenCode is the active runtime, the Runtime Adapter maps AiosDeck Skills into OpenCode's native skill system. Skills are loaded before each agent task:

```
Agent executes task
   │
   ├── Runtime Adapter loads skills
   │     └── opencode skill load <name>
   │
   ├── Runtime Adapter sends prompt
   │     └── opencode "prompt"
   │
   └── Runtime Adapter parses result
```

When OpenCode is the active runtime, Skills are discovered by OpenCode from:
- `.opencode/skills/<name>/SKILL.md` (project-level)
- `~/.config/opencode/skills/<name>/SKILL.md` (user-level)
- `.claude/skills/<name>/SKILL.md` (Claude-compatible)
- `.agents/skills/<name>/SKILL.md` (agent-compatible)

### Core Skills for AiosDeck

| Skill | Purpose |
|-------|---------|
| `project-dna` | Project identity, architecture, conventions |
| `coding-style` | Code conventions, naming, organization |
| `project-context` | Automatic context injection (future) |

### Tool Integration

OpenCode provides tools that agents use:
- File operations (read, write, edit)
- Shell execution (`bash` tool)
- Web fetching (`webfetch` tool)
- Git operations (if configured)

When OpenCode is the active runtime, AiosDeck does not wrap these tools. It delegates to OpenCode's native tool system.

### Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
runtime:
  adapter: opencode
  command: "ai-jail opencode"
```

OpenCode configuration (providers, models, permissions) is managed separately in `~/.config/opencode/opencode.json` or `.opencode/opencode.json`.

### Headless Mode Security

When running headless (no interactive terminal), the Runtime Adapter enforces strict tool permissions to prevent silent timeouts. Any tool that requires human interaction (e.g., `question`) will hang the subprocess.

To prevent this, the adapter injects the `OPENCODE_PERMISSION` environment variable before every invocation:

```json
{
  "question": "deny"
}
```

The permission model is binary: `"allow"` or `"deny"` — never `"ask"` (which requires interactive approval).

#### Per-Agent Tool Lockdown

Permissions are derived from each agent's `required_capabilities`:

| Agent | Capabilities | Tool Permissions |
|-------|-------------|-----------------|
| PlannerAgent | `filesystem_read` | `question: deny`, `edit: deny`, `bash: deny` |
| DeveloperAgent | `filesystem_read`, `filesystem_write`, `shell` | `question: deny` |

This ensures:
- The **question** tool is never available (no human to answer).
- The **Planner** (read-only) cannot modify files or execute shell commands.
- The **Developer** retains full tool access except `question`.

Permissions are cached by capabilities set in the adapter, avoiding repeated JSON serialization.

## Consequences

- OpenCode is a runtime dependency of the current adapter. Without OpenCode (or another compatible runtime adapter), AiosDeck cannot execute agents.
- AiosDeck does not reimplement OpenCode features (tools, skill loading, model abstraction) — the adapter maps to them.
- If OpenCode evolves, only the Runtime Adapter needs updating. If a different runtime becomes primary, the adapter is the only thing that changes.

## Implementation Notes

- [x] Runtime Adapter must detect OpenCode installation: `which opencode`
- [x] Runtime Adapter must invoke OpenCode through ai-jail: `ai-jail opencode`
- [x] Skill names passed to OpenCode must match directory names in skills paths
- [x] Prompt construction: task description + context packet + instructions
- [x] Result parsing: extract text output, files changed, errors from OpenCode output
- [x] Test: OpenCode installed → adapter reports available
- [x] Test: OpenCode not installed → critical error
- [x] Test: skill not found → warning logged, execution continues
- [x] Inject `OPENCODE_PERMISSION` env var with `question: deny` in headless mode
- [x] PlannerAgent gets `edit: deny, bash: deny` via capabilities check
- [x] Permission JSON cached by capabilities set for performance
