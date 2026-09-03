# AiosDeck Roadmap — v1.2 → v3.0

**Status**: Proposed
**Date**: 2026-09-03
**Supersedes**: the "Implementation Roadmap" table in [README.md](README.md) (its
items are absorbed into M1 below).

Format: **Milestones** are versioned releases with an integration gate
(full suite + mutation score ≥ baseline + `benchmark compare` within budget).
**Epics** are independently verifiable missions with their own acceptance
criteria. **Issues** are tasks executable by one workflow.

## Status Legend

| Marker | Meaning |
|---|---|
| ✅ `implemented` | shipped and covered by tests |
| 🔶 `in-progress` | open issue with work started or queued for the milestone |
| 🟦 `planned` | accepted into the milestone; no implementation exists yet |
| ⬜ `proposed` | direction agreed; may be re-scoped by the evidence gate |

> **Nothing marked 🟦/⬜ is real yet.** Each epic must earn implementation via
> TDD against its acceptance criteria. Do not cite planned epics as system
> capabilities in other docs.

## Current State (evidence, v1.1.0)

Implemented: Kernel + Event Bus, Context Engine (layers), Memory (SQLite),
specialized agents (Planner/Developer/Reviewer/Tester/Documentation/Git/
Research) on a shared AgentExecutor with lifecycle
`created → validated → queued → running → succeeded|failed|timed_out|cancelled`,
Workflow engine (plan→implement→review→test→docs→commit), Backlog Runner
(sequential, reuses `Kernel.run(mode="plan-run")`), Kanban/Scrum Scheduler,
replaceable runtimes (OpenCode + Ollama adapters, preflight diagnostics),
capability-based security with ai-jail, quality gates, telemetry + versioned
benchmark schema with baselines and `benchmark compare`, RuleBasedRouter,
Skills/Knowledge/Retrieval/Learning (embryonic), TUI dashboard with the ocean
theme, CLI. ~1600 tests, mutmut + pytest-gremlins nightly.

Missing: Mission model, Scope Engine, Mission Planner, Mission Graph,
Capability Registry (task-side), Dynamic Teams, execution Advisor, RLM,
supervision policies, remote interfaces, self-development, and a visual
design system.

## The Flappy Bird Incident (architectural evidence)

A self-hosted run (clone Flappy Bird) exposed four coupled failure modes:

1. a `manual_qa` task was routed to the Developer agent, which cannot do
   browser/GUI validation — it burned the full 600 s timeout;
2. timeout is a single hardcoded 600 s wall (`runtime/opencode.py`), with no
   step-level limits and no process supervision;
3. user cancellation (Ctrl+C) did not stop fallback: the Router cascaded
   Qwen → Gemini → Ollama after the user had explicitly aborted;
4. shutdown is not graceful: `AgentExecutor.cancel()` is best-effort
   ("running work is not hard-killed") and `pool.shutdown(wait=True)` at
   interpreter teardown raised `SystemExit` inside the shutdown callback.

This is documented as [ADR-0007](decisions/ADR-0007-flappy-bird-incident.md)
(observed evidence separated from proposed solutions) and drives M1's P0
epics (E1.5–E1.8) and M2's E2.5. The lesson: **do not increase timeouts —
teach the system what kind of task it is running, what capabilities the task
requires, and how to stop without hanging the kernel.**

---

## M1 — v1.2 · Hardening + Kernel Stability

Close the open v1.x work and fix the demonstrated reliability gaps. Nothing
new above the current execution model ships in this milestone.

| Epic | Focus | Status | Issues |
|---|---|---|---|
| E1.1 | Routing correctness: propagate planner complexity to RuntimeEngine; observe effective routing | 🔶 | #92 |
| E1.2 | Execution-Environment Awareness (ExecutionEnvironment model, detector, runtime context, sandbox signaling, PromptBuilder, validation) | 🔶 | #84–#89 |
| E1.3 | Performance governance: CLI lazy loading, cache contract → ContextCache, performance budgets → CI regression gate → benchmark history | 🔶 | #42–#47 |
| E1.4 | Verification debt: self-hosted workflow with Ollama llama3.2 in CI; residual mutmut survivors classified; ocean profile view | 🔶 | #78, #91, #60 |
| **E1.5** | **Cancellation & Graceful Shutdown** — cooperative cancellation token propagating Kernel → AgentExecutor → Runtime → subprocesses; SIGINT ≠ SIGTERM ≠ internal timeout; no `SystemExit` in atexit/shutdown callbacks; shutdown with its own deadline (kill children when it expires); Ctrl+C cancels exactly once and exits 130 | 🟦 | [#94](https://github.com/GabrielPabloG/aiosdeck/issues/94)–#98 |
| **E1.6** | **Execution Reliability: Timeouts + Process Supervision** — per-task-type timeouts (e.g. `quick_test 60s`, `unit_test 120s`, `build 300s`, `browser_qa 300s`, `large_refactor 600s`) replacing the single hardcoded 600 s; step-level timeouts (`shell_command`, `model_turn`, `process_start`); timeout → cancel → kill child processes → collect diagnostics → `TIMEOUT` with last action recorded | 🟦 | [#99](https://github.com/GabrielPabloG/aiosdeck/issues/99)–#102 |
| **E1.7** | **Resilient Fallback** — fallback budget (`max_attempts`, `max_total_time`) and retry classification (`retry_on: provider_error, runtime_error`; **never** retry `user_cancelled` or `capability_missing`); every fallback observable in telemetry | 🟦 | [#104](https://github.com/GabrielPabloG/aiosdeck/issues/104)–#106 |
| **E1.8** | **Execution State + Telemetry** — richer task states (`PENDING/READY/RUNNING/COMPLETED/FAILED/TIMEOUT/BLOCKED/CANCELLED/SKIPPED`) mapped onto the **existing** executor lifecycle (no competing model); structured failure records (category, agent, runtime, model, elapsed, fallback attempts, cancelled_by_user); events `task_started/task_timeout/runtime_fallback/runtime_cancelled/agent_cancelled/kernel_shutdown`; "why did this task take 600 s" answerable from telemetry alone | 🟦 | [#108](https://github.com/GabrielPabloG/aiosdeck/issues/108)–#111 |

E1.5 + E1.6 may ship early as a **v1.1.2 hotfix** — they are user-facing
stability bugs and nothing else in M1 blocks them.

**Release gate**: full suite + nightly mutation without regression +
`benchmark compare` inside the E1.3 budget + a CI integration test that
sends SIGINT mid-execution and asserts termination within its deadline with
no lingering threads.

## M2 — v1.3 · Mission Intelligence + Capability-Aware Planning

Demonstrated problem: `ad plan` knows only TASK; multi-workflow missions are
orchestrated by the human; tasks are dispatched without asking whether the
system can perform them at all (ADR-0007).

| Epic | Focus | Status |
|---|---|---|
| E2.1 · [#112](https://github.com/GabrielPabloG/aiosdeck/issues/112) | **Mission Contract** — `Mission` model (intent, constraints, acceptance criteria, artifacts, replanning history), mission states, `mission.*` events on the existing bus, SQLite persistence. Tasks keep the AgentExecutor lifecycle | 🟦 |
| E2.2 | **Scope Engine** — semantic complexity and affected-universe inventory (modules, tests, config, security boundaries, perf-sensitive paths). Never prompt length | 🟦 |
| E2.3 | **Complexity Assessment** — `DIRECT_WORKFLOW` vs `DECOMPOSED_MISSION`, decision explainable and telemetry-recorded | 🟦 |
| E2.4 | **Mission Planner** — decomposition into tasks with objective/scope/deps/acceptance/artifacts/verification/capabilities; routes to existing workflows only (no graph yet) | 🟦 |
| **E2.5** · [#117](https://github.com/GabrielPabloG/aiosdeck/issues/117) | **Capability-Aware Planning & Routing** — task taxonomy; tasks declare required capabilities; Capability Registry reports what the system can actually do (observed, not config-inferred); Router matches task → capable agent or `BLOCKED` with an explanation; fallback by capability, not only by model; Planner answers "is this even possible?" before queueing | 🟦 |

### Capability Distinction (architectural invariant)

Two different notions of "capability" exist and **must not be merged**:

| | `security/capabilities.py` | E2.5 Capability Registry |
|---|---|---|
| Question | What is this agent **allowed** to do? | What can the system **actually provide** for this task? |
| Nature | Authorization (enforcement, zero-trust) | Observation (detection, routing) |
| Mutates? | Grants/revokes per agent policy | Read-only view of runtime/sandbox/tool availability |

The Registry never authorizes anything and never substitutes
`CapabilityEnforcer`. Names may overlap only where semantics genuinely match.
The Planner consumes the Registry to decide routing and `BLOCKED`; the
Security Manager consumes capabilities to decide permission.

**Release gate**: synthetic mission set classified correctly;
DIRECT_WORKFLOW behaves identically to today's pipeline (backward compat);
a `manual_qa`-style task with no browser capability returns `BLOCKED` in
<1 s instead of timing out in 600 s.

## M3 — v1.4 · Graph Engineering (Workflow + Backlog unification)

Demonstrated problem: BacklogRunner is a flat sequential list — no
dependencies, no parallelism, no artifact/failure propagation.

| Epic | Focus | Status |
|---|---|---|
| E3.1 | Mission Graph — dependency edges (`BLOCKING/PRODUCER/CONSUMER/OPTIONAL`), cycle validation, topological order | 🟦 |
| E3.2 | Graph Runner — evolve BacklogRunner into graph execution **reusing Workflow + AgentExecutor**; no duplicated pipeline | 🟦 |
| E3.3 | Parallel execution where safe + artifact propagation producer→consumer + failure propagation | 🟦 |
| E3.4 | Minimal replanning — retry / amend / reorder / abort / escalate; `capability_missing` and `user_cancelled` are **non-retryable** (consumes E1.7/E2.5); never restart the whole mission | 🟦 |
| E3.5 | Mission Acceptance — `MISSION_COMPLETE` requires tasks + tests + mutation + gates + reviewer + performance budget; functional and performance results reported separately | 🟦 |

**Release gate**: one real decomposed mission executed end-to-end by the
Graph Runner with failure injection demonstrating replanning.

## M4 — v1.5 · Dynamic Teams + QA/Tester Architecture + Mission Context

| Epic | Focus | Status |
|---|---|---|
| E4.1 | Team Composition — `Mission → Tasks → required capabilities → composed agents`; teams are compositions, not a new runtime; every member on the same AgentExecutor | 🟦 |
| E4.2 | Scoped Mission Context — task-relevant context + artifacts + retrieved knowledge; never full mission history to every agent | 🟦 |
| E4.3 | Mission Observability — per-mission tokens/cost/duration/retries/replanning/human interventions | 🟦 |
| **E4.4** · [#122](https://github.com/GabrielPabloG/aiosdeck/issues/122) | **Specialized Agent Roles** — official boundaries: Developer writes code; Tester runs tests; QA/Browser interacts with the running application; Reviewer evaluates. Planner/Router assigns roles via E2.5. Ends Developer-as-do-everything | 🟦 |
| **E4.5** · [#125](https://github.com/GabrielPabloG/aiosdeck/issues/125) | **Validation DSL** — declarative, machine-checkable acceptance criteria produced by the Planner (e.g. `game_starts`, `keyboard_flap`, `collision_ends_game`, `fps >= 55`, `viewports: [desktop, mobile]`), executed by the Tester, consumed by Mission Acceptance (E3.5). Replaces "do a manual validation" | 🟦 |

**Release gate**: benchmark of the same mission with/without scoped context
(tokens + success rate, measured); a Validation-DSL spec executed by Tester
on a real web artifact.

## M5 — v2.0 · Advisor + RLM + Browser QA Engine

| Epic | Focus | Status |
|---|---|---|
| E5.1 | Execution Advisor — analyzes telemetry, failures, cost, effective routing, benchmark history; emits **proposals** only (`Advisor → Proposal → approval/policy → execution`) | 🟦 |
| E5.2 | Project Graph — structural graph (modules→dependencies→tests→docs) shared by Scope Engine and RLM; not a disconnected subsystem | 🟦 |
| E5.3 | RLM — iterative reasoning over relevant subgraphs: scoped retrieval → compression → selective expansion. A reasoning strategy, not a generic agent | 🟦 |
| **E5.4** · [#128](https://github.com/GabrielPabloG/aiosdeck/issues/128) | **Browser QA / Computer Interaction Engine** — new engine **inside ai-jail** (browser sandbox is a new security capability class, never an exception): start server, open app, click/keyboard/touch, screenshots, console/network logs, performance metrics, desktop/mobile viewports, smoke tests. Registered in the Capability Registry (E2.5). Hard preconditions: E1.5/E1.6 (supervised cancellation) + E2.5 + E4.5 | ⬜ |

**Release gate**: a mission on an external project (ProjDesk/RagDocs) where
the RLM-assisted plan beats the non-RLM plan in measured cost **and** success
rate; browser QA smoke test passing inside the sandbox with cancellation
verification.

## M6 — v2.1 · Supervision + Verification-Earned Autonomy

| Epic | Focus | Status |
|---|---|---|
| E6.1 | Human Gates — `AUTO / SUPERVISED / APPROVAL_REQUIRED` per risk class: architecture changes, dependency changes, security policy, destructive ops, merge, capability escalation. Routine work needs no interaction | 🟦 |
| E6.2 | Self-Development Benchmark — harness over real historical issues (e.g. #38→#64, #79→#90, the ADR-0007 incident) + synthetic ones; measures mission success rate, decomposition quality, retries, replanning, interventions, cost, test/mutation/perf/security regressions, reviewer acceptance. E1.8 failure categories feed the dataset | 🟦 |
| E6.3 | Autonomy Escalation — policy upgrades per domain only when E6.2 metrics cross a documented threshold; rollback/recovery explicit | 🟦 |

**Release gate**: a public, versioned success-rate number. This gate is a
hard precondition for M8.

## M7 — v2.2 · Remote Interfaces

| Epic | Focus | Status |
|---|---|---|
| E7.1 | Mission API — single programmatic surface (`submit/status/diff/logs/cancel/approve/review`); interfaces never duplicate orchestration | 🟦 |
| E7.2 | Telegram Gateway — `Telegram → Gateway → Mission API → Policy → Core`; explicit authn/authz at the new trust boundary; **never** `Telegram → shell`; never bypasses Planner/Scope/capabilities/ai-jail/gates | 🟦 |
| E7.3 | Remote Supervision UX — approvals, diffs, mission logs, replanning via events; approving an E6.1 gate remotely is the central use case | 🟦 |

**Release gate**: dedicated abuse test suite (command injection, out-of-scope
paths, capability escalation, destructive ops without approval).

## M8 — v3.0 · Controlled Self-Development

Hard precondition: E6.2 metrics supporting autonomy. No privileged path.

| Epic | Focus | Status |
|---|---|---|
| E8.1 | AiosDeck-as-Project — the repo registered as a regular project/workspace: same manifest, capabilities, ai-jail, gates. Zero special self-modification code | 🟦 |
| E8.2 | Self-Dev Loop — `Mission → Scope → Graph → Workflows → tests → mutation → benchmarks → review → human approval → merge` executed on the repo under existing branch governance | 🟦 |
| E8.3 | Learning Governance — `Observation → candidate → confidence → Advisor/policy → approval → memory/architecture`, applied to patterns mined from its own missions (E5.1 consumes E1.8 failure telemetry) | 🟦 |

## Track D — Design System "Control Room" (parallel)

The submarine-control-room identity already exists in code
(`ui/theme.py` ocean palette: abyss/deep/surf/foam/sky/ice + info/success/
warning/danger accents) but has no visual contract: no system design, no
wireframes, no shared token source. That is why the product looks
inconsistent. Track D fixes the contract, then the implementations follow
their milestones.

| Epic | Focus | Ships with | Status |
|---|---|---|---|
| D1 · [#132](https://github.com/GabrielPabloG/aiosdeck/issues/132) | System Design & Penpot artifacts — architecture diagrams (blocks, mission sequence, depth layers, **cancellation flow as a target contract**), TUI wireframes (Mission Control, Sonar, Control Room, Mission Log, Deep Dive), web wireframe, `style-guide.md`, `tokens.json` as single source of design truth | M1 | 🟦 (artifacts created; validation pending) |
| D2 | Design tokens as code — `tokens.json` → `theme.py` (generated/validated); TUI aligned to the Mission Control wireframe; #60 inherits the visual vocabulary | M2 | 🟦 |
| D3 | Control Room implemented — Mission Control, Sonar, Mission Log, Deep Dive screens consuming mission/graph state | M4 | 🟦 |
| D4 | Web UI — consumes the Mission API (E7.1), reuses Penpot artifacts + tokens | M7 | 🟦 |

Artifacts live in [design/](design/). Diagrams must reflect real invariants
(ai-jail between Runtime and agent processes, hub-and-spoke Event Bus, shared
SQLite ConnectionPool); where a diagram shows desired-not-yet-built behavior
(e.g. cancellation flow) it is explicitly annotated as a **contract**, not a
description.

---

## Dependency Order

```
M1: E1.5+E1.6+E1.7 (P0) ──► E1.8 ─────────┐
                                          ▼
M2: E2.1 Mission Contract ─ E2.2/2.3/2.4 ──► E2.5 Capability Router
                                              │
M3: E3.1–E3.5 Graph (consumes E1.7/E1.8/E2.5) │
                                              ▼
M4: E4.1–E4.3 Teams/Context ─ E4.4 Roles ──► E4.5 Validation DSL
                                              │
M5: E5.1 Advisor ─ E5.2/5.3 RLM ──────────► E5.4 Browser QA Engine
                                              │
M6: E6.1 Gates ─ E6.2 Benchmark (E1.8 data) ─► E6.3 Escalation
                                              │
M7: E7.1 Mission API ─ E7.2/7.3 Telegram ◄────┘
M8: E8.1–E8.3 Self-Development (requires E6.2 evidence)
Track D: D1 (M1) → D2 (M2) → D3 (M4) → D4 (M7)
```

## Explicitly Rejected / Deferred (§40 discipline)

| Tempting proposal | Decision | Reason |
|---|---|---|
| Raise timeout to 900/1200 s | **NO-GO** | Symptom, not cause; task type, cancellation, and fallback cascade stay broken |
| New task-state model separate from executor | **NO-GO** | E1.8 extends the existing lifecycle only |
| Browser QA before E2.5/E1.5 | **NO-GO** | Capability without registry + cancellation = zombies and security risk |
| Graph before M3 | deferred | Flat backlog works; abstraction needs a demonstrated dependency problem |
| Teams before M4 | deferred | Static workflows still cover execution |
| Telegram in M1–M5 | deferred | Interface over an unsupervised core creates a trust boundary without gates |
| Marketplace / Team Mode / Cloud Gateway / IDE integration | deferred | No demonstrated problem |

## North Star (M2–M5)

Move from *"agents that execute tasks"* to *"a system that understands the
kind of task, knows which capabilities exist, picks the right agent,
supervises execution, cancels correctly, and can explain why something could
not be done."*

> **Less friction. More intelligence.**
