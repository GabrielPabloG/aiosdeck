# ADR-0003 — Event Bus Architecture

**Status**: Implemented
**Level**: Architecture
**Review date**: 2026-08-09
**Date**: 2026-08-02

## Context

AiosDeck has multiple components — Kernel, Context Engine, Memory Engine, Security Manager, Quality Pipeline, Scheduler, Agents, Runtime Adapter. These components must communicate. We had to choose between direct function calls (tight coupling) and an event-driven architecture (loose coupling).

We evaluated three patterns:

| Option | Description |
|--------|-------------|
| **Direct function calls** | Components import and call each other's methods directly |
| **Event Bus (in-process)** | Components communicate through a centralized pub/sub dispatcher |
| **External message broker** | Redis, NATS, or RabbitMQ for inter-component messaging |

## Decision

**Use an in-process event bus with topic-based pub/sub.** Components publish events to topics and subscribe to topics they care about. No component knows about any other component. The Event Bus is the only component that knows all routes.

The bus is in-process for v0.1 through v1.0. External message brokers are a post-v1.0 concern for distributed deployment. The in-process bus uses `asyncio` for non-blocking delivery.

## Consequences

### Positive

- **Loose coupling**: Components are independently testable. A Context Engine test does not need a Memory Engine.
- **Observability**: Every interaction passes through one point. Audit logging, debugging, and tracing are centralized.
- **Extensibility**: New subscribers can be added without modifying publishers. The Quality Pipeline can subscribe to agent events without the agent knowing.
- **Gradual complexity**: In-process bus is simple. External broker complexity is deferred until needed.

### Negative

- **Indirection cost**: Event-driven systems are harder to trace end-to-end than direct function calls.
- **No delivery guarantees**: If a subscriber crashes during event processing, the event is lost. No retry, no dead-letter queue in v0.1.
- **Schema coordination**: Publishers and subscribers must agree on event payload schemas. Schema changes require coordination.

### Neutral

- The event bus is an in-process async dispatcher. This is sufficient for single-machine deployment. Distributed messaging is a post-v1.0 concern.
- Events are fire-and-forget. If request-response semantics are needed (e.g., approval gates), they are modeled as two events (request + response), not RPC.
