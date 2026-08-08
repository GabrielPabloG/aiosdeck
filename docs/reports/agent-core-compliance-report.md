# Agent Core Compliance Report — v0.9.2

**Date**: 2026-08-08
**PR**: 6 — Agent Core Hardening
**Branch**: `feature/agent-core-hardening`
**Version**: 0.9.2

This report is populated from the actual test run. Every verdict below is
produced by the contract, integration, and architecture suites — a category is
only ✅ when its automated check passes.

## Verification run

```
pytest  → 334 passed
ruff check  → all checks passed
ruff format --check  → clean
```

Suites specific to this PR (82 tests):

| Suite | Files | Result |
|-------|-------|--------|
| Contract tests | `tests/contracts/test_agent_contracts_matrix.py` + `test_agent_contracts.py` | ✅ passed |
| Integration via AgentExecutor | `tests/integration/test_agent_executor_integration.py` | ✅ passed |
| Executor boundary | `tests/test_executor.py` | ✅ passed |
| Architecture checks | `tests/architecture/test_agent_architecture.py` | ✅ passed |

## Per-agent compliance matrix

Legend: ✅ pass, ❌ fail. Categories: **Contract** (execute signature /
AgentTask in, AgentResult out), **Executor** (runs exclusively via
AgentExecutor, executor-free agent), **Lifecycle** (validated state machine),
**Events** (agent.* lifecycle events with standardized payload), **Errors**
(AgentError mapping + timeout/retry policy), **Capabilities** (declared set
matches canonical policy; read-only guard), **Architecture** (no runtime
bypass, no orchestration coupling).

| Agent | Contract | Executor | Lifecycle | Events | Errors/Timeout/Retry | Capabilities | Architecture |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Planner | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Researcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Developer | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reviewer | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tester | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Documentation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Git | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Declared contract per agent

| Agent | Timeout | Retry (max_attempts) | Capabilities |
|-------|:---:|:---:|-------|
| Planner | 360s | 2 (TIMEOUT, RUNTIME_ERROR) | filesystem_read, ask_user |
| Researcher | 60s | 1 (no retry) | filesystem_read |
| Developer | 600s | 1 (no retry) | filesystem_read, filesystem_write, shell |
| Reviewer | 60s | 1 (no retry) | filesystem_read |
| Tester | 180s | 1 (no retry) | filesystem_read, shell |
| Documentation | 30s | 1 (no retry) | filesystem_read, filesystem_write |
| Git | 90s | 1 (no retry) | git |

## Execution-boundary invariants (architecture checks)

1. **Agent → AgentExecutor: impossible.** No agent module imports or references
   the executor. Recursion is structurally prevented. ✅
2. **Workflow/CLI → rich domain APIs: forbidden.** `WorkflowEngine`,
   `Kernel.run()`, and the `review`/`research` CLI commands route exclusively
   through `execute()` / `Kernel.run_agent()`. Rich APIs are private. ✅
3. **Runtime → outside the adapter: forbidden.** The runtime is reached only
   through the runtime adapter, inside `agent.execute()`. ✅
4. **Lifecycle/execution events: single producer.** A project-wide scan confirms
   only `AgentExecutor` publishes `agent.lifecycle.changed` and all
   `agent.execution.*` topics. ✅
5. **Legacy vocabulary removed.** No `agent.execution.finished` /
   `AGENT_EXECUTION_FINISHED` references remain in `src/`. ✅

## Standardized lifecycle

```
created → validated → queued → running → succeeded | failed | timed_out | cancelled
                                        └→ running (retry)
```

- `queued` = the agent was accepted by the system but has not yet started
  consuming execution (ready for scheduler/concurrency).
- `created → created` is the **initialization event**, not a state transition:
  it guarantees every execution emits a complete, deterministic sequence.
- Terminal states are immutable.

## Two-tier event model

| Tier | Topic | Purpose |
|------|-------|---------|
| Lifecycle | `agent.lifecycle.changed` | Every state transition (with `previous_state`/`current_state`) |
| Execution | `agent.execution.started/progress/completed/failed/timed_out/retried/cancelled` | Execution observability |

Every event shares the contract: `event_id`, `agent`, `task_id`,
`correlation_id`, `executor_id` (per instance), `sequence` (per execution),
`attempt`, `status`, `duration_ms`, `error_code`, `message`. Fields are
nullable per event (e.g., `agent.execution.started.duration_ms = null`,
`agent.execution.completed.error_code = null`, `agent.execution.retried.attempt = N`).
`sequence` orders events deterministically; `attempt` identifies the execution
attempt; the two are never conflated.

## Error codes

`VALIDATION_ERROR`, `RUNTIME_ERROR`, `PERMISSION_DENIED`, `TIMEOUT`,
`CANCELLED`, `UNKNOWN`. Retry is applied only to transient (`retryable`)
errors whose code is in the agent's `retry_policy.retryable_codes`. The
default policy is **no retry** (`max_attempts=1`).

## Verdict

All seven agents pass contract tests, integration tests via `AgentExecutor`,
and architecture checks. The execution core is standardized and the
single-throat invariant is enforced by automated tests, ready for
observability (Usage/Telemetry) on top.
