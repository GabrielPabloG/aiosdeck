# CLI Philosophy

**Status**: Accepted
**Date**: 2026-08-02
**Target Version**: v0.5 (DX)

## Context

AiosDeck inherited its kernel architecture from a carefully engineered foundation: event bus, context
engine, memory engine, security skeleton — all wired through a precise initialization order.

What it did not inherit was a *user experience philosophy*. The v0.1 CLI exposed the kernel's
internal lifecycle directly: `aios start`, `aios status`, `aios exit`. These are accurate
descriptions of what the kernel does. They are not descriptions of what the user wants.

This document establishes the CLI's design principles before any new command is added. It answers the
three questions that determine whether a CLI feels like a tool or like an SDK.

## Decision

### 1. What is the primary noun?

**Task** — hidden behind free-text intent, exactly as ProjDesk hides "Workspace" behind `pd <name>`.

Nobody types `pd workspace my-project`. They type `pd my-project`. The noun vanishes into the
argument. The same applies here: nobody will type `aios task create "add jwt auth"`. They will type
`aios "add jwt auth"`. The text becomes a Task inside the kernel; "Task" only resurfaces explicitly
when the user needs to refine (`list`, `continue`, `status`).

This is not a new concept. Task, Task Queue, and Agent.execute(task) already exist in the codebase
(`src/aios/agents/__init__.py`). We are promoting something already built from internal detail to
user-facing contract.

Agent, Runtime, and Memory are the engine — not the steering wheel. The user never "uses" the
Planner or Reviewer directly. They use the result of their work.

### 2. What commands does a user use every day?

Eight. No more. Prioritized by what exists in the kernel today:

| Command | Purpose | Exists today? |
|---------|---------|---------------|
| `aios` (no args) | Dashboard — replaces `start` + `status` | Kernel already ready |
| `aios "intent"` | Execute full pipeline (Plan → Implement → Review → Test → Document → Commit) | Deferred to v0.7 (requires Planner + Pipeline) |
| `aios plan "<intent>"` | Plan only, no code changes | Deferred to v0.4 (requires Planner) |
| `aios review` | Review current diff | Deferred to v0.5 (requires Reviewer) |
| `aios test` | Quality Pipeline isolated | Deferred to v0.6 (requires Quality Pipeline) |
| `aios memory list\|add\|forget\|search` | Manage project knowledge | Memory Engine exists today |
| `aios doctor` | Diagnostics | Context + health checks exist today |
| `aios config` | Configuration management | Config Engine exists today — deferred (no real demand yet) |

**Rule**: A command is only exposed if its backing component exists and functions. Never show a
command that produces "coming soon." Never let the user type something that doesn't work. If a
component doesn't exist yet, the command doesn't appear in the tree.

### 3. What can be inferred automatically and never asked?

| What | How | Already built? |
|------|-----|---------------|
| Project location | cwd detection; `pd resolve <name>` via ProjDesk subprocess | Context Engine detects from cwd |
| Language, tools, Git, Docker | Detection pipeline (Python, JS, Shell detectors) | Context Engine v0.1 |
| Memory from previous sessions | SQLite restore on kernel start | Memory Engine v0.3 skeleton |
| Which workflow to run | Intent classification from free text | Deferred (requires Planner v0.4) |
| Locale / output language | System `$LANG`, same as ProjDesk | Not yet — inherit ProjDesk behavior |
| Permissions already granted | Policy Engine per-agent capabilities | Security skeleton exists, enforcement v0.6 |

### Primary verb

The user's primary verb is **resolve** — not start, not configure, not manage. They want something
done. Every command that doesn't end with a resolved outcome is scaffolding. Scaffolding is necessary
but must be kept to a minimum and hidden behind simpler verbs.

### When to ask vs. when to infer

| Situation | Action |
|-----------|--------|
| Can be detected from filesystem | Detect. Never ask. |
| Can be restored from previous session | Restore. Offer to change. |
| Requires architecture decision | Ask. Humans Own the Architecture. |
| Destructive operation (push, delete, migrate) | Block. Approval Gate. |
| Ambiguous intent (multiple interpretations) | Offer choice. Never guess. |

### Command Registry pattern

Commands are registered, not hardcoded:

```
aios/cli/commands.py  →  COMMANDS = { ... }
aios/cli/completion.py  →  reads COMMANDS, generates suggestions
aios/cli/main.py  →  reads COMMANDS, dispatches
```

Every command exposes `name`, `description`, `aliases`, `subcommands`, and `execute()`. The CLI
parser, the help system, and the autocomplete engine all consume the same registry. Adding a command
means adding one entry — not touching three files.

This is the foundation for future plugins: registering a new Command at runtime without modifying the
parser.

## Consequences

### Positive

- **Consistency**: Every user-facing feature has one source of truth (the Command Registry).
- **Discoverability**: `aios help` and `aios <TAB>` show exactly the same tree.
- **Honesty**: No command appears before its backing component exists.
- **Simplicity**: Adding a command is one entry in the Registry, not changes across four files.
- **ProjDesk alignment**: Detection over prompts, semantic tree over flat list, nouns over verbs.

### Negative

- **Slower feature exposure**: Commands are hidden until their engines are ready. Users may not know
  what's coming.
- **Registry overhead**: Every new command must implement the Command protocol, even simple ones.

### Neutral

- The Registry pattern is not a plugin system yet. It will become one in v0.9 when external plugins
  can register commands.
- Shell completion scripts are thin wrappers. Intelligence lives in Python (`aios __complete`). This
  is intentional — the completion scripts are shell-specific glue, not duplicated logic.

## Implementation Notes

- [ ] `docs/cli-philosophy.md` — this document
- [ ] `src/aios/cli/commands.py` — Command protocol + Registry
- [ ] `src/aios/cli/completion.py` — autocomplete engine consuming Registry
- [ ] `completion/bash.sh` — thin wrapper calling `aios __complete`
- [ ] `completion/zsh.sh` — thin wrapper calling `aios __complete`
- [ ] `src/aios/cli/main.py` — rewritten CLI surface consuming Registry
- [ ] `__complete` must not appear in `--help` output
- [ ] `start`, `status`, `exit` remain functional as hidden aliases
- [ ] `tests/test_cli.py` updated for new command surface
- [ ] `tests/test_completion.py` — new tests for completion engine
