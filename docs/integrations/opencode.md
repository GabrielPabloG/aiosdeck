# OpenCode Integration

**Status**: Draft
**Date**: 2026-08-02

## Context

OpenCode is the primary agent runtime for AiosDeck. It provides: a CLI interface for agent interaction, a native skill system for loading reusable knowledge, tool execution (file operations, shell commands), and model provider abstraction (Ollama, OpenAI, Anthropic, Google).

AiosDeck does not compete with OpenCode. It extends it. OpenCode is the execution engine; AiosDeck is the orchestration layer above it.

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

AiosDeck uses OpenCode's native skill system. Skills are loaded before each agent task:

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

Skills are discovered by OpenCode from:
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

AiosDeck does not wrap these tools. It delegates to OpenCode's native tool system.

### Configuration

```yaml
# ~/.config/aiosdeck/config.yaml
runtime:
  adapter: opencode
  command: "ai-jail opencode"
```

OpenCode configuration (providers, models, permissions) is managed separately in `~/.config/opencode/opencode.json` or `.opencode/opencode.json`.

## Consequences

- OpenCode is a runtime dependency. Without it, AiosDeck cannot execute agents.
- AiosDeck does not reimplement OpenCode features (tools, skills, model abstraction).
- If OpenCode evolves, only the Runtime Adapter needs updating.

## Implementation Notes

- [ ] Runtime Adapter must detect OpenCode installation: `which opencode`
- [ ] Runtime Adapter must invoke OpenCode through ai-jail: `ai-jail opencode`
- [ ] Skill names passed to OpenCode must match directory names in skills paths
- [ ] Prompt construction: task description + context packet + instructions
- [ ] Result parsing: extract text output, files changed, errors from OpenCode output
- [ ] Test: OpenCode installed → adapter reports available
- [ ] Test: OpenCode not installed → critical error
- [ ] Test: skill not found → warning logged, execution continues
