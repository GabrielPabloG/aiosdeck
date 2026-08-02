# Scheduler

**Status**: Draft
**Date**: 2026-08-02

## Context

As AiosDeck grows beyond a single agent, it needs a component that manages which agent runs when, in what order, and with what priority. The Scheduler receives tasks, queues them, and dispatches them to the correct agent.

The Scheduler is introduced in v0.8 when the system supports multiple concurrent agents. In earlier versions (v0.1–v0.7), task dispatch is a simple sequential call handled by the Kernel.

## Decision

### Architecture

```
Workflow Engine  ──► task.created ──► Scheduler
                                          │
                                          ├── Priority Queue
                                          │     ├── high
                                          │     ├── medium
                                          │     └── low
                                          │
                                          ├── Dispatch Logic
                                          │     └── Maps task.type → agent.name
                                          │
                                          └── Concurrency Manager
                                                └── Limits concurrent agent count
```

### Task Lifecycle

```
Created ──► Queued ──► Dispatched ──► Running ──► Completed
                │                       │
                │                       ├──► Failed ──► Retrying (max 3)
                │                       │
                └──► Cancelled          └──► Timed out
```

### Task Schema

```python
@dataclass
class Task:
    id: str                           # UUID
    type: str                         # code, review, test, document, git, research
    priority: TaskPriority            # high, medium, low
    workflow_id: str                  # parent workflow (nullable)
    agent_requirement: str            # agent name or "any"
    payload: dict                     # task-specific data
    status: TaskStatus                # created, queued, dispatched, running, completed, failed
    retries: int = 0
    max_retries: int = 3
    timeout: int = 300                # seconds
    created_at: datetime
    assigned_agent: str | None = None
    completed_at: datetime | None = None
```

### Priority Queue

Tasks are ordered by:
1. Priority (high > medium > low)
2. Creation time (FIFO within same priority)

```python
class PriorityQueue:
    def enqueue(self, task: Task) -> None: ...
    def dequeue(self) -> Task | None: ...
    def requeue(self, task: Task) -> None: ...  # retry
    def cancel(self, task_id: str) -> None: ...
    def peek(self) -> Task | None: ...
    def size(self) -> int: ...
```

### Dispatch

The Scheduler maps task types to agents:

```python
AGENT_MAP = {
    "code": "coder",
    "review": "reviewer",
    "test": "tester",
    "document": "documentation",
    "git": "git",
    "research": "researcher",
}
```

When a task is dequeued, the Scheduler:
1. Finds the correct agent by type
2. Checks if the agent is available (not busy)
3. Assigns the task to the agent
4. Emits `task.dispatched`

### Concurrency

The Scheduler supports running multiple agents concurrently (v0.8+):

```python
class Scheduler:
    max_concurrent_agents: int = 3

    async def _dispatch_loop(self) -> None:
        while self.active_agents < self.max_concurrent_agents:
            task = self.queue.dequeue()
            if task is None:
                break
            agent = self._resolve_agent(task)
            if agent and await agent.is_available():
                self.active_agents += 1
                asyncio.create_task(self._run_task(task, agent))
```

### Retry Logic

Failed tasks are retried up to 3 times with exponential backoff:

```
Attempt 1 → fail → wait 2s
Attempt 2 → fail → wait 4s
Attempt 3 → fail → wait 8s
Attempt 4 (final) → fail → emit task.failed (permanent)
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` | Consumed | New task enters the queue |
| `task.dispatched` | Emitted | Task assigned to an agent |
| `agent.completed` | Consumed | Task succeeded |
| `agent.errored` | Consumed | Task failed, may retry |
| `task.completed` | Emitted | Task finished successfully |
| `task.failed` | Emitted | Task failed permanently (max retries exhausted) |
| `task.retrying` | Emitted | Task retry initiated |

### Workflow Integration

Workflows submit tasks to the Scheduler:

```python
# Workflow Engine
await bus.publish("task.created", Task(
    type="code",
    priority=TaskPriority.HIGH,
    workflow_id=workflow.id,
    payload={"files": ["src/auth.py"], "description": "Implement OAuth2 login"},
))
```

The Scheduler receives the task and manages its lifecycle. The Workflow Engine listens for `task.completed` and `task.failed` to advance or abort the workflow.

## Consequences

### Positive

- **Scalability**: Supports multiple concurrent agents without additional infrastructure.
- **Reliability**: Retry logic with backoff handles transient failures.
- **Visibility**: Every task transition emits an event. Queue depth and agent load are observable.
- **Decoupling**: Agents are unaware of scheduling. They receive tasks and produce results.

### Negative

- **Complexity**: Queue management, retry, timeout, and concurrency add significant code.
- **No persistence**: v0.8 Scheduler is in-memory. System restart loses the queue. Persistent queues are post-v1.0.
- **Single process**: Concurrency is async-based. True parallel execution requires process-based agents.

### Neutral

- The Scheduler runs in the same process as the Kernel. Distributed scheduling is a post-v1.0 concern.
- Task priorities are advisory. No preemption. A running task completes before a higher-priority task starts.

## Implementation Notes

- [ ] Implement `scheduler/engine.py` — Scheduler class with dispatch loop and retry logic
- [ ] Implement `scheduler/queue.py` — PriorityQueue with enqueue/dequeue/cancel/requeue
- [ ] Task schema: UUID id, priority enum, status enum, retry count, timeout
- [ ] Concurrency limit: configurable via config (default 3)
- [ ] Retry: exponential backoff (2^n seconds), max 3 retries
- [ ] Timeout: if a task runs longer than its timeout, cancel it and emit task.failed
- [ ] Queue must be observable: expose `queue.size()` and `queue.peek()` for debugging
- [ ] Test: enqueue 3 tasks → dequeue returns highest priority first
- [ ] Test: task fails → retries 3 times → permanent failure after max retries
- [ ] Test: task succeeds → emits task.completed → queue removes task
- [ ] Test: concurrency limit respected (only N tasks running simultaneously)
