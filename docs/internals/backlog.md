# Backlog Runner

The backlog runner processes N tasks from a backlog automatically. Each task
triggers one `plan-run` workflow, producing one conventional commit, with
telemetry and kanban tracking.

## Concepts

- **BacklogTask** — a single task parsed from a conventional commit title
  (`type(scope): subject (vX.Y.Z)`).
- **BacklogRunner** — sequentially executes tasks through `Kernel.run` with
  `mode="plan-run"`, `create_branch=False`, and a commit factory derived from
  the parsed title.
- **Source** — tasks come from a kanban board's `Todo` column (`board:NAME`)
  or a `TODO.md` file (`file:PATH`).

## CLI Usage

```bash
# Run all tasks from the "backlog" kanban board
aios backlog run --source=board:backlog

# Run from a file, continuing on error, resuming from index 3
aios backlog run --source=file:TODO.md --continue --from 3

# List tasks from a file
aios backlog list file:TODO.md

# Add a task to the kanban board
aios backlog add "feat(backlog): add feature (v0.9.13)" --board backlog

# Show backlog telemetry
aios backlog stats
aios backlog stats --json
```

## Flags

| Flag | Description |
|------|-------------|
| `--source=board:NAME` | Load tasks from kanban board `NAME` (Todo column) |
| `--source=file:PATH`  | Load tasks from markdown file with `- [ ]` lines |
| `--continue`          | Keep running despite task failures |
| `--from N`            | Resume from task index N (0-based) |
| `--json`              | Output stats as JSON |

## Architecture

```
CLI → BacklogRunner.run()
        ↓
  for each task:
    parse_conventional(title) → (type, scope, subject, version)
    build_commit_factory()    → f"type(scope): subject (version)"
    kanban.begin_work(card)
    Kernel.run(task, context, mode="plan-run", create_branch=False)
    kanban.complete_work(card) | kanban.block_card(card)
    TelemetryEngine ← backlog.* events
```

All modules are under `src/aios/backlog/`:

- `models.py` — `BacklogTask`, `BacklogRunResult`
- `parser.py` — `parse_conventional`, `load_tasks_from_kanban`,
  `load_tasks_from_file`
- `runner.py` — `BacklogRunner`
- `cli.py` — CLI command handlers