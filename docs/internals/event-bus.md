# Event Bus

**Status**: Accepted
**Date**: 2026-08-02

## Context

AiosDeck is an event-driven system. Every component — Kernel, Context Engine, Memory Engine, Security Manager, Quality Pipeline, Scheduler, Agents, Runtime Adapter — communicates exclusively through events. Without a reliable, well-defined Event Bus, the system cannot function.

The Event Bus must be: simple (no external dependencies), typed (events have schemas), asynchronous (non-blocking publish), and observable (all events are loggable for debugging).

## Decision

### Architecture

The Event Bus follows a **topic-based pub/sub** model with an in-process dispatcher:

```
Publisher ──► EventBus.publish(topic, payload) ──► Dispatcher
                                                      │
                                                      ├──► Subscriber A (topic X)
                                                      ├──► Subscriber B (topic X)
                                                      └──► Subscriber C (topic Y)
```

Topics are dot-separated hierarchical strings. Subscribers register interest in a topic. Publishers fire events without knowing who subscribes.

### Topic Hierarchy

```
session
├── session.start
├── session.ready
└── session.shutdown

context
├── context.detected
└── context.error

memory
├── memory.loaded
├── memory.updated
└── memory.error

task
├── task.created
├── task.dispatched
├── task.completed
├── task.failed
└── task.retrying

agent
├── agent.started
├── agent.completed
├── agent.errored
├── agent.skill_loaded
├── agent.execution.started
├── agent.execution.finished
└── agent.execution.failed

quality
├── quality.started
├── quality.gate_passed
├── quality.gate_failed
└── quality.completed

security
├── security.violation
├── security.approval_requested
├── security.approval_granted
└── security.approval_denied

workflow
├── workflow.started
├── workflow.stage_changed
├── workflow.completed
└── workflow.failed

runtime
├── runtime.ready
├── runtime.error
└── runtime.disconnected

system
├── system.health_check
├── system.error
└── system.shutdown
```

### Event Schema

Every event carries:

```python
@dataclass
class Event:
    topic: str              # e.g. "task.created"
    payload: Any            # event-specific data
    timestamp: datetime     # when the event was created
    correlation_id: str     # ties events to a session or workflow run
```

Wildcard subscriptions are supported: subscribing to `task.*` receives all task events. Exact subscriptions receive only matching topics.

### API

```python
class EventBus:
    async def publish(self, topic: str, payload: Any) -> None: ...
    async def subscribe(self, topic: str, handler: Callable) -> None: ...
    async def unsubscribe(self, topic: str, handler: Callable) -> None: ...
    def subscriber_count(self, topic: str) -> int: ...
```

### Implementation

The v0.1 Event Bus is an in-process async dispatcher. No message broker, no network layer, no persistence. Events are delivered to subscribers in the same process using `asyncio`:

```python
class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    async def publish(self, topic: str, payload: Any) -> None:
        event = Event(topic=topic, payload=payload, ...)
        handlers = self._resolve_handlers(topic)
        await asyncio.gather(*(h(event) for h in handlers))

    def _resolve_handlers(self, topic: str) -> list[Callable]:
        exact = self._subscribers.get(topic, [])
        wildcard = []
        for pattern, handlers in self._subscribers.items():
            if pattern.endswith("*") and topic.startswith(pattern[:-1]):
                wildcard.extend(handlers)
        return exact + wildcard
```

Future versions (post v1.0) may support external message brokers (Redis, NATS) for distributed deployment. The `EventBus` interface remains unchanged — only the implementation is swapped.

### Integration with Audit Logger

Every event published is also forwarded to the Audit Logger:

```python
async def publish(self, topic: str, payload: Any) -> None:
    event = Event(...)
    await self._audit_logger.log(event)     # non-blocking
    await self._dispatch(event)             # normal delivery
```

The Audit Logger appends to a structured log file. No event is silently dropped.

### Error Handling

Subscriber errors must not crash the dispatcher or affect other subscribers:

```python
async def _dispatch(self, event: Event) -> None:
    tasks = []
    for handler in self._resolve_handlers(event.topic):
        tasks.append(self._safe_call(handler, event))
    await asyncio.gather(*tasks, return_exceptions=True)

async def _safe_call(self, handler: Callable, event: Event) -> None:
    try:
        await handler(event)
    except Exception as e:
        logging.error(f"Subscriber error for {event.topic}: {e}")
```

## Consequences

### Positive

- **Decoupling**: Components know nothing about each other. Only the topic contract matters.
- **Observability**: Every interaction passes through one point. Debugging is straightforward.
- **Testability**: Components are tested with a mock EventBus. No integration required for unit tests.
- **Extensibility**: New subscribers can be added without modifying existing publishers.

### Negative

- **Indirection**: An event-driven system is harder to trace end-to-end than direct function calls.
- **No delivery guarantees**: If a subscriber crashes, the event is lost. No retry, no dead-letter queue.
- **Ordered delivery**: Events are delivered in publication order within the same async context, but no guarantees across async boundaries.

### Neutral

- The in-process bus is sufficient for single-machine deployment. Distributed messaging is a post-v1.0 concern.
- Event schemas are Python dataclasses. Changing a schema requires coordination between producer and consumer.

## Implementation Notes

- [ ] Implement `event_bus/events.py` — Event dataclass and all payload type definitions
- [ ] Implement `event_bus/dispatcher.py` — EventBus class with publish/subscribe
- [ ] Event payloads must be serializable to JSON for logging
- [ ] Wildcard subscriptions (`task.*`) must resolve correctly
- [ ] Subscriber errors must be caught and logged; never propagate to callers
- [ ] Audit Logger integration: every published event must be written to structured log
- [ ] Test: publish event → all matching subscribers receive it
- [ ] Test: subscriber error → other subscribers still receive the event
- [ ] Test: unsubscribe → subscriber no longer receives events
- [ ] Test: wildcard subscription matches exact topics correctly
