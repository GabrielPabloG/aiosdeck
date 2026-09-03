# ADR-0007 — Flappy Bird Incident: Capability-Aware Execution & Cancellation Contract

**Status**: Proposed
**Level**: Architecture
**Type**: Incident evidence + directional decision
**Date**: 2026-09-03

## Purpose of this ADR

This record separates **what was observed** from **what is proposed**. The
observations are facts from a real self-hosted run. The proposals are not
implemented; they become the acceptance evidence for epics E1.5–E1.8 and E2.5
in [roadmap.md](../roadmap.md). Cite the observations as evidence; cite the
proposals only as direction.

## Context

AiosDeck executed a self-hosted mission: "clone Flappy Bird". The Planner
decomposed it into 10 tasks. Tasks 1–8 (implementation, unit-level testing)
succeeded through the Developer agent. Task 9 was:

> "Validação manual/EA de gameplay" (manual/gameplay validation)

The platform had no concept of what that task *required*. It dispatched it to
the Developer agent, which has no browser, no GUI interaction, and no visual
observation ability. The task consumed its entire 600 s timeout. Then a
cancellation cascade occurred. The full observed sequence:

```
Planner → 10 tasks
Developer 1–8 → OK
Developer 9 (manual QA) → timeout 600s
  fallback → Gemini → begins investigating the project
  user presses Ctrl+C → runtime exit 130
  fallback → Ollama   (retry AFTER the user cancelled)
  user presses Ctrl+C again
Kernel shutdown
  ThreadPoolExecutor waits on live threads
  SystemExit raised inside the threading/atexit shutdown path
```

## Observed facts (evidence)

1. **Task type was invisible to routing.** The Planner emitted a `manual_qa`
   task; the Router had no notion of task requirements and delivered it to
   the only code-writing agent available. There was no check of whether the
   task was possible in the current environment.
2. **Timeout is a single undifferentiated wall.**
   `src/aios/runtime/opencode.py` hardcodes `600` s for the whole task. There
   is no distinction between task-level, step-level (`shell_command`,
   `model_turn`, `process_start`), or task-type expectations. A 60 s smoke
   test and a 600 s refactor share the same budget.
3. **Timeout does not stop execution cleanly.** On timeout the future is
   abandoned; child processes spawned by the agent (dev servers, watchers)
   are not reliably terminated; no diagnostics (last action, running
   processes) are collected at the moment of failure.
4. **Cancellation is best-effort by design.**
   `src/aios/agents/executor.py` documents `cancel()` as *"Best-effort:
   running work is not hard-killed"*. Nothing propagates cancellation into
   the runtime or its subprocesses.
5. **Fallback ignores user intent.** After Ctrl+C (exit 130), the Router
   treated the abort as a provider failure and fell back Qwen → Gemini →
   Ollama. The fallback chain in `src/aios/routing/engine.py` has no
   `max_attempts`/`max_total_time` budget and no retry classification
   (`user_cancelled` was indistinguishable from `provider_error`).
6. **Shutdown is not graceful.** `AgentExecutor.shutdown()` calls
   `pool.shutdown(wait=True, cancel_futures=True)`; during interpreter
   teardown the join on live threads surfaced `SystemExit: 0` inside the
   threading shutdown path ("Exception ignored on threading shutdown").
   Ctrl+C therefore does not reliably terminate the kernel in one motion.
7. **Execution state was too coarse to explain the incident.** The user saw
   "8/10 tasks completed". Neither the task records nor telemetry could
   answer "why did task 9 take 600 s, what was it doing, and who retried
   it?" — the data simply was not structured anywhere.

## What this incident is NOT

- It is **not** evidence that 600 s is too short. Raising the timeout would
  have produced the same outcome with more waste.
- It is **not** a model-quality problem. The fallback providers behaved as
  configured; the configuration was the problem.
- It is **not** an ai-jail defect. The sandbox did its job; nothing escaped.

## Proposed decisions (not yet implemented)

Each maps to a roadmap epic; none is adopted as current system behavior by
this ADR.

1. **Capability-aware planning & routing (E2.5).** Tasks declare required
   capabilities (`browser`, `interaction`, `visual_observation`,
   `performance_measurement`, …). A Capability Registry — *observation of
   what the system can actually do* — is consulted before execution. No
   capable agent ⇒ `BLOCKED` with an explanation, immediately, instead of a
   600 s timeout. Fallback becomes capability-based, not model-only.
   - **Invariant**: the Registry is distinct from
     `src/aios/security/capabilities.py`. Security capabilities **authorize**
     agents (enforcement); the Registry **describes** the environment
     (routing). The Registry never grants permission and never replaces the
     `CapabilityEnforcer`.
2. **Role boundaries (E4.4).** Developer writes code; Tester runs tests;
   QA/Browser interacts with running applications; Reviewer evaluates. The
   Planner/Router assigns by role.
3. **Declarative validation (E4.5).** "Verificar 60fps" becomes machine-
   checkable criteria (`game_starts`, `keyboard_flap`, `fps >= 55`,
   `viewports: [desktop, mobile]`) produced by the Planner and executed by
   the Tester.
4. **Hierarchical timeouts + supervision (E1.6).** Per-task-type budgets and
   step-level limits; timeout triggers cancel → kill child processes →
   collect diagnostics → mark `TIMEOUT` — never an abandoned thread.
5. **Cooperative cancellation contract (E1.5).** The desired flow —
   represented visually in
   [`docs/design/penpot/04-fluxo-cancelamento.svg`](../design/penpot/04-fluxo-cancelamento.svg)
   **as a contract, not as current behavior**:

   ```
   Ctrl+C → CANCEL_REQUESTED → cancel agents → cancel futures
          → terminate child processes → flush telemetry
          → kernel shutdown → exit 130   (exactly once)
   ```

   SIGINT, SIGTERM, and internal timeout are distinct causes;
   `SystemExit` must never be raised inside atexit/shutdown callbacks.
6. **Fallback budget & classification (E1.7).** `max_attempts`,
   `max_total_time`, `retry_on: [provider_error, runtime_error]`,
   `don't_retry_on: [user_cancelled, capability_missing]`. A user
   cancellation is a decision, not a failure, and never triggers fallback.
7. **Rich execution state + telemetry (E1.8).** Task states extend the
   existing executor lifecycle (`timed_out`/`cancelled` already exist);
   failure records carry category/agent/runtime/model/elapsed/fallback
   context; events `task_started/task_timeout/runtime_fallback/
   runtime_cancelled/agent_cancelled/kernel_shutdown` make every incident
   answerable from structured data.

## Consequences

### Positive

- Impossible tasks fail fast with explanations instead of burning budgets.
- Ctrl+C becomes a trustworthy operation; the kernel terminates in one
  motion, once.
- Incidents become datasets: E6.2's self-development benchmark can consume
  real failure categories instead of synthetic anecdotes.
- The system starts to be *aware of its own capabilities* — the prerequisite
  for safe autonomy (verification before autonomy).

### Negative

- More moving parts in the execution path (registry, budgets, cancellation
  propagation); each must be covered by tests before it is trusted.
- Capability detection is environment-dependent and can be wrong; `BLOCKED`
  messages must be actionable, not mysterious.
- Per-task-type timeout tables need maintenance and will be contested; they
  must stay benchmark-informed (§28), never folklore.

### Neutral

- The Flappy Bird run doubles as the reference integration scenario for
  E1.5–E1.8 and E2.5 acceptance criteria.
- Nothing in this ADR changes what currently ships in v1.1.0.

## References

- [roadmap.md](../roadmap.md) — M1 (E1.5–E1.8), M2 (E2.5), M4 (E4.4/E4.5), M5 (E5.4)
- ADR-0002 — ai-jail as security sandbox (browser QA in E5.4 stays inside this boundary)
- ADR-0003 — Event Bus architecture (cancellation and execution events flow through the bus)
- Issue #92 — planner complexity not propagating to RuntimeEngine (follow-up: capability propagation under E2.5)
