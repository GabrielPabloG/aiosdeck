# Scheduler — Kanban Engine

**Status**: In Progress (v0.8.0)
**Date**: 2026-08-02 (updated 2026-08-05)

## Context

The Scheduler manages the lifecycle of development work: which cards exist, where
they are in the flow, what must happen before a card is done. In v0.8 the Scheduler
is implemented as a **persistent Kanban Engine** with Scrum columns — a durable,
verifiable task board rather than a transient in-memory queue.

This decision follows the project philosophy — *every abstraction must solve an
existing problem, never an anticipated one*. AiosDeck runs agents sequentially
today, so a concurrent dispatch queue would solve no existing problem. The problem
that existed was persistence and verification of work, solved by the Kanban Engine.
See [ADR-0006](../decisions/ADR-0006-kanban-scrum-scheduler.md).

## Decision

### Architecture

```
Kernel ──► KanbanEngine (scheduler)
                │
                ├── SQLiteStore (kanban_ tables in .aios/memory.db)
                │     ├── kanban_boards     (id, name, status, project_id)
                │     ├── kanban_cards      (id, board_id, title, column, tdd_gate)
                │     └── kanban_subtasks   (id, card_id, description, done)
                │
                ├── Column flow validation
                ├── TDD gate enforcement
                └── Terminal rendering (ProgressSpinner, render_kanban)
```

### Domain Model

| Concept | Description |
|---------|-------------|
| `KanbanBoard` | A sprint. Has a name and a status (`active`). Scoped to a project. |
| `KanbanCard` | A unit of work on the board. Always in exactly one column. |
| `KanbanSubtask` | A sub-item of a card (e.g., the failing-test step of the TDD cycle). |
| `KanbanError` | Domain error for flow violations. Hides SQLite from callers. |

### Columns

```
Backlog → Todo → InProgress → Review → Done
```

Rules enforced by `move_card(card_id, column)`:

- Forward moves advance exactly **one** column.
- Backward moves (rework) are allowed at any depth.
- Skipping forward (e.g., `Backlog → InProgress`) raises `KanbanError`.
- Unknown columns raise `KanbanError`.

### TDD Gate

The TDD gate is the structural enforcement of the Red → Green cycle:

1. A card enters `InProgress` with a subtask `failing test (RED)` — the Red step.
2. Execution runs against the card while it is `InProgress`.
3. On success (Green achieved), the flow:
   - completes the RED subtask,
   - moves the card to `Review`,
   - calls `pass_tdd_gate(card_id)`,
   - moves the card to `Done`.

A card **cannot** be moved to `Done` while `tdd_gate` is `False`. The store rejects
the transition with a `KanbanError` regardless of how the caller reaches it.

### API

```python
engine = KanbanEngine(project_path=project, db_path=...)  # defaults to .aios/memory.db
engine.initialize()

board = engine.create_board("Sprint 1")
card = engine.create_card(board_id=board.id, title="Add OAuth2 login")
engine.move_card(card.id, "Todo")
subtask = engine.create_subtask(card_id=card.id, description="failing test (RED)")
engine.move_card(card.id, "InProgress")
# ... execute ...
engine.complete_subtask(subtask.id)
engine.move_card(card.id, "Review")
engine.pass_tdd_gate(card.id)
engine.move_card(card.id, "Done")

engine.list_cards(board.id)  # board state for rendering
engine.list_boards()  # all sprints for this project
engine.shutdown()
```

### Planner/Executor Integration

`aios plan <intent> --run` drives the Kanban Engine:

1. A sprint board is created from the intent.
2. Each planned subtask becomes a card in `Backlog`.
3. Cards move `Todo → InProgress` with a RED subtask.
4. On success, cards complete the TDD cycle and land in `Done`.
5. On failure, the loop stops (fail-fast) and the board is rendered, showing
   exactly where the work stalled.

The board render is a non-blocking summary written to stderr:

```
  📋 Sprint Board
  Backlog (0) | Todo (0) | InProgress (1) | Review (0) | Done (2)
```

### Event Contract

The Kanban Engine publishes domain events to the Event Bus:

| Topic | Payload | When |
|-------|---------|------|
| `kanban.card_moved` | card_id, card_title, from_column, to_column, board_id | A card changes column |
| `kanban.card_blocked` | card_id, card_title, reason, column, board_id | A card fails the TDD gate or is blocked (`block_card`) |
| `kanban.subtask_created` | subtask_id, card_id, description | A subtask (e.g., RED step) is added |
| `kanban.subtask_completed` | subtask_id | A subtask is completed |

`block_card(card_id, reason)` persists the blocked state (`blocked`, `block_reason`)
on the card — it stays in its origin column — and emits `kanban.card_blocked`.
Attempting to move a card to `Done` without a green TDD gate also emits
`kanban.card_blocked` before raising `KanbanError`.

## Next Steps (v0.9+)

The original Scheduler spec — a concurrent priority queue with agent dispatch —
remains valid as future work, building **on top of** the Kanban Engine rather than
replacing it.

### Priority Queue

```
Workflow Engine ──► task.created ──► Scheduler
                                        │
                                        ├── Priority Queue (high / medium / low)
                                        ├── Dispatch Logic (task.type → agent.name)
                                        └── Concurrency Manager
```

### Task Lifecycle

```
Created ──► Queued ──► Dispatched ──► Running ──► Completed
                │                       │
                │                       ├──► Failed ──► Retrying (max 3)
                └──► Cancelled          └──► Timed out
```

### Planned Behaviors

- Concurrent agent execution (`max_concurrent_agents`, default 3)
- Retry with exponential backoff (2^n seconds, max 3 retries)
- Per-task timeout with cancellation
- Observable queue (`queue.size()`, `queue.peek()`)

## Consequences

### Positive

- **Persistent**: The board survives restarts and doubles as the sprint audit trail.
- **Verifiable**: The TDD gate makes "done" a structural property, not an assertion.
- **Zero dependencies**: SQLite via the standard library.
- **Single database**: Memory and Kanban share `.aios/memory.db`.

### Negative

- **Single-writer**: SQLite serializes writes; fine while agents run sequentially.
- **Strict flow**: Forward-by-one moves may not fit every process. Custom columns
  are a future concern.
- **No concurrency yet**: Parallel agent dispatch is deferred to v0.9+.

### Neutral

- The store abstraction isolates the backend. Only `scheduler/store.py` knows SQLite.
- Queueing and dispatch, when they arrive, will consume and extend this engine.

## Implementation Notes

- [x] Implement `scheduler/engine.py` — `KanbanEngine` (name = "scheduler"), Engine protocol
- [x] Implement `scheduler/store.py` — SQLite store with WAL, FKs, 3 kanban tables
- [x] Implement `scheduler/models.py` — `KanbanBoard`, `KanbanCard`, `KanbanSubtask`, `KanbanError`, `COLUMNS`
- [x] Column flow validation — forward by one, backward free, skip rejected
- [x] TDD gate — `move_card(..., "Done")` blocked until `pass_tdd_gate()`
- [x] Planner integration — `plan --run` creates sprint, cards, TDD cycle
- [x] Terminal DX — `ProgressSpinner`, `log_step`, `render_kanban`
- [x] Register in Kernel `INIT_ORDER` and CLI kernel factory
- [x] Test: board create/retrieve, project isolation
- [x] Test: card move through the full flow
- [x] Test: TDD gate blocks `Done` without green tests
- [x] Test: TDD gate allows `Done` after `pass_tdd_gate`
- [x] Test: invalid column and skip transitions raise `KanbanError`
- [x] Test: persistence across sessions and sessions reopened on same DB
- [x] Emit kanban domain events (`kanban.card_moved`, `kanban.card_blocked`, `kanban.subtask_*`)
- [x] Blocked state — `block_card` persists `blocked`/`block_reason`, live board alert `⛔ Blocked`
- [x] Backlog prepopulation — `plan --run` renders the full plan and `Backlog (N)` before executing
- [x] E2E test — `tests/test_cli_e2e.py` validates DB state and Event Bus over a real kernel
- [ ] Priority queue with concurrent agent dispatch — v0.9
