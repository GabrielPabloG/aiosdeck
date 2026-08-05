# Planner Agent

**Status**: Accepted (Implemented in v0.6)
**Date**: 2026-08-04
**Introduced**: v0.6

## Context

Complex tasks require decomposition. "Add user authentication" is not a single task — it involves database migrations, API endpoints, middleware, tests, documentation. The Planner agent breaks high-level goals into concrete, ordered tasks that other agents can execute.

The Planner does not write code. It does not execute Git. It does not modify files. Its only job is to think, decompose, and prioritize. This constraint is intentional: separation of planning from execution prevents scope creep and ensures human oversight.

## Decision

### In → Process → Out

```
In:  Task (type: "plan", payload: {goal: "Add OAuth2 login"})
     Context Packet (project structure, conventions, architecture)
     Skills: ["project-dna"]

Process:
  1. Load project context and architecture knowledge
  2. Decompose goal into subtasks
  3. Order subtasks by dependency (database → API → middleware → tests)
  4. Estimate complexity for each subtask
  5. Identify risks and unknowns
  6. Output structured task list

  Delegates execution to AgentExecutor (v0.5+).
  The Executor provides Event Bus publishing, metrics,
  and (future) timeout/retry.

Out: AgentResult with list of Tasks ready for Scheduler
```

### Output Format

```python
{
    "goal": "Add OAuth2 login",
    "subtasks": [
        {
            "id": "task-001",
            "type": "code",
            "description": "Add OAuth2 dependency to pyproject.toml",
            "priority": "high",
            "dependencies": [],
            "estimated_complexity": "low",
        },
        {
            "id": "task-002",
            "type": "code",
            "description": "Create OAuth2 configuration module (src/auth/config.py)",
            "priority": "high",
            "dependencies": ["task-001"],
            "estimated_complexity": "medium",
        },
        {
            "id": "task-003",
            "type": "code",
            "description": "Implement OAuth2 provider integration (src/auth/provider.py)",
            "priority": "high",
            "dependencies": ["task-002"],
            "estimated_complexity": "high",
        },
        {
            "id": "task-004",
            "type": "code",
            "description": "Add auth middleware (src/auth/middleware.py)",
            "priority": "medium",
            "dependencies": ["task-003"],
            "estimated_complexity": "medium",
        },
        {
            "id": "task-005",
            "type": "test",
            "description": "Write tests for auth module",
            "priority": "medium",
            "dependencies": ["task-003", "task-004"],
            "estimated_complexity": "medium",
        },
        {
            "id": "task-006",
            "type": "documentation",
            "description": "Update README with OAuth2 setup instructions",
            "priority": "low",
            "dependencies": ["task-003"],
            "estimated_complexity": "low",
        },
    ],
    "risks": [
        "OAuth2 provider API may have rate limits",
        "Session management needs secure cookie configuration",
    ],
    "unknowns": [
        "Which OAuth2 providers are needed? (Google, GitHub, ...)",
    ],
}
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: plan) | Consumed | Receive a planning task |
| `task.created` (type: code, test, docs, review) | Emitted | One event per subtask created |

### Required Capabilities

- `filesystem_read` — to understand project structure and existing code

### Cannot

- Write code
- Execute Git commands
- Access the internet
- Run shell commands
- Modify files

### Required Skills

- `project-dna` — must understand project identity, architecture, conventions
- `coding-style` — must propose tasks that align with code conventions

### Future (v0.9+)

- Parallel subtask generation for independent tasks
- Complexity estimation based on historical task data (Memory Engine)
- Risk detection from known mistake patterns (Memory Engine)
- Human-AI collaborative planning (approval gate for task acceptance)
- Emit `task.created` events per subtask consumed by the concurrent Scheduler (v0.9+)

## Consequences

### Positive

- **Structured output**: Plans are machine-readable. The Scheduler consumes subtasks directly.
- **Dependency awareness**: Tasks are ordered correctly. No agent gets an impossible task.
- **Separation of concerns**: The Planner never executes. The Coder never plans.
- **Oversight**: Human reviews the plan before execution begins.

### Negative

- **Latency**: Planning adds a stage before any code is written.
- **Accuracy**: Planner output depends on context quality. Poor context → poor plan.
- **No learning**: v0.6 Planner does not learn from past plans. Memory Engine integration in future.

### Neutral

- The Planner is optional. Simple tasks bypass planning and go directly to the Coder.
- Plan approval can be automated for low-risk tasks in future versions.

## Implementation Notes

- [x] Implement `agents/planner.py` — PlannerAgent class
- [x] Planner output parsed as JSON via `_parse_plan()`
- [x] Subtask dependencies must form a DAG (no cycles)
- [x] Planner delegates to AgentExecutor for timeout/retry guardrails
- [x] Planner cannot modify files — enforced by capabilities + OPENCODE_PERMISSION
- [x] Test: simple goal → structured subtask list with dependencies
- [x] Test: empty input → Planner produces valid output
- [x] Test: Planner cannot write files (capability check)
- [x] Test: Planner parses JSON from markdown and text wrappers
- [x] Kanban integration: `aios plan <intent> --run` creates a sprint board, one
  card per subtask, and drives the TDD gate cycle (RED subtask → green → Done)
