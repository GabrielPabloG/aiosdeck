# ADR-0006 — Kanban with Scrum for Scheduler Persistence

**Status**: Implemented
**Level**: Architecture (borders on Implementation — includes SQL schema and spinner terminal DX details)
**Review date**: 2026-08-09
**Date**: 2026-08-05

## Context

The Scheduler (v0.8) must manage the lifecycle of development work in a way that
is observable, verifiable, and durable. Three requirements drove the design:

1. **Persistence across sessions.** A plan executed today must leave a trace that
   survives a restart. Work that was started must not vanish with the process.
2. **TDD enforcement.** The flow must require a test cycle (Red → Green) before a
   card can be considered done. Moving work to `Done` without the TDD gate must be
   structurally impossible, not a matter of policy.
3. **Visual feedback.** The developer needs clear, non-blocking progress in the
   terminal — animated spinners instead of static status text.

The original Scheduler spec proposed an in-memory priority queue with concurrent
agent dispatch. That spec anticipated a problem that did not yet exist: AiosDeck
runs agents sequentially. Per the project philosophy — *every abstraction must
solve an existing problem, never an anticipated one* — the Scheduler was built
around the problem that actually existed: persistent, verifiable task flow.

We evaluated three storage approaches:

| Option | Description |
|--------|-------------|
| **In-memory priority queue** | Queued tasks with retry logic and concurrency, lost on restart |
| **Redis / external queue** | Durable queue as a service |
| **SQLite kanban board** | Persistent boards, cards, and subtasks in the project database |

## Decision

**Model the Scheduler as a persistent Kanban board with Scrum columns, stored in
SQLite** — the same database file used by the Memory Engine (`.aios/memory.db`),
isolated behind dedicated `kanban_*` tables.

### Columns

```
Backlog → Todo → InProgress → Review → Done
```

A card moves forward one column at a time. Backward moves (rework) are allowed.
Skipping forward more than one column raises a `KanbanError`.

### TDD Gate

A card cannot move to `Done` unless its TDD gate has been passed
(`tdd_gate = True`). The gate is the structural enforcement of the Red → Green
cycle: a card enters `InProgress` with a failing-test subtask (`failing test (RED)`),
and only when the execution succeeds (tests green) does the flow complete the
subtask, reach `Review`, pass the gate, and move to `Done`.

### Data Model

```
kanban_boards    (id, name, status, project_id, created_at)
kanban_cards     (id, board_id, title, description, column_name, tdd_gate, project_id, created_at, updated_at)
kanban_subtasks  (id, card_id, description, done, created_at)
```

### Terminal DX

Static progress text is replaced by a `ProgressSpinner` (animated braille frames
on TTY, single-line fallback otherwise) plus `log_step` status lines and a
`render_kanban` board summary at the end of execution.

## Consequences

### Positive

- **Persistent**: Work survives restarts. The board is the audit trail of a sprint.
- **Zero new dependencies**: Reuses `sqlite3` from the standard library.
- **One database per project**: Memory and Kanban share `.aios/memory.db`, keeping
  the project self-contained.
- **TDD enforced structurally**: The gate is a validation rule in the store, not a
  convention agents are asked to follow.
- **Non-blocking DX**: Spinners and progress logs keep the terminal live without
  locking the user out.

### Negative

- **Single-writer**: SQLite serializes writes. Acceptable while agents run
  sequentially (v0.8). A concurrent dispatch model would need WAL tuning or a
  different store.
- **Schema growth**: The project database now holds 4 memory tables plus 3 kanban
  tables. Migration scripts must be maintained.
- **Column model is rigid**: Strict forward flow by one column may not fit every
  team's process. Custom columns are a future concern.

### Neutral

- The concurrent priority queue is deferred to **v0.9+** as a separate concern.
  The Kanban Engine is the Scheduler today; queueing and parallel dispatch will
  build on top of it rather than replace it.
- The store abstraction isolates the storage backend — `scheduler/store.py` is the
  only module that knows about SQLite.
