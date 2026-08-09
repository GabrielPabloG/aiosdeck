# Developer Agent (formerly "Coder")

**Status**: Implemented (as `developer.py`)
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Introduced**: v0.2

## Context

This document was originally the "Coder Agent" specification. The "Coder" name
was never implemented — the implementation agent is **`developer.py`**
(`DeveloperAgent`), which ships as the primary implementation agent of AiosDeck.

The planned Coder role — a single-responsibility agent that writes and modifies
code without planning, reviewing, testing, or committing — is filled by the
Developer agent. The other responsibilities were split into dedicated agents
(Planner, Reviewer, Tester, Documentation, Git, Research) rather than into a
separate "Coder".

## Current Implementation

`DeveloperAgent` lives in `src/aios/agents/developer.py`. It:

- Receives an `AgentTask` (type `code`) and a context packet.
- Delegates execution to the **AgentExecutor** (`ExecutionRequest` →
  `ExecutionOutcome`), the single execution boundary. It is executor-free:
  it never holds or calls an executor itself.
- Runs through the runtime (OpenCode via ai-jail) and returns an `AgentResult`.
- Declares capabilities `filesystem_read`, `filesystem_write`, `shell`
  (see `tests/agent_compliance_matrix.py`).

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `agent.execution.started` | Emitted | Executor began the run |
| `agent.execution.completed` | Emitted | Code written successfully |
| `agent.execution.failed` | Emitted | Code generation failed |
| `agent.lifecycle.changed` | Emitted | Lifecycle transition (via executor) |

### Cannot

- Plan tasks (that is the Planner's job)
- Review code (that is the Reviewer's job)
- Execute Git commands (that is the Git agent's job)
- Access the internet (that is the Researcher's job)
- Run tests (that is the Tester's job)

## Consequences

### Positive

- **Single responsibility**: writes code, nothing else.
- **Security**: capability-bound; cannot push, cannot delete projects, cannot
  access the network.
- **Centralized execution**: the AgentExecutor applies timeout, retry, and
  lifecycle uniformly.

### Neutral

- Code generation quality depends on the underlying LLM. The Developer agent is
  an orchestrator, not a model.

## Migration Note

Refer to the Developer agent's real contract and capabilities in
[`tests/agent_compliance_matrix.py`](../../tests/agent_compliance_matrix.py) and
[`src/aios/agents/developer.py`](../../src/aios/agents/developer.py).
