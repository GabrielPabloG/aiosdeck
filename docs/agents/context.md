# Context Agent

**Status**: Implemented
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Introduced**: v0.1 (built-in, not user-facing)

## Context

The Context Engine is documented in [phases/phase-02-context.md](../phases/phase-02-context.md). It is a system engine, not a user-facing agent. This document exists for architectural completeness — the Context component is part of the agent ecosystem but operates as infrastructure, not as a task-receiving worker.

## Decision

The Context component is not an agent. It is an **engine** — initialized at session start, running before any agent execution, and emitting a standardized context packet consumed by all agents. It does not receive tasks from the Scheduler. It does not execute via the Runtime Adapter.

### Relationship to Agents

- All agents consume the Context Packet
- The Context Engine enriches agent prompts with project-specific knowledge
- Context is detected fresh each session
- Memory (v0.3) enriches context with persisted knowledge

## Consequences

- Documented here for architectural completeness
- No implementation notes — see `phases/phase-02-context.md`
