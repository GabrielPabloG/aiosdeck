# Changelog

All notable changes to AiosDeck are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Scheduler now writes `TODO.md` (textual backlog with checkboxes + spinner)
  instead of rendering the Kanban board to stderr during `plan --run`. The
  Kanban visual display is deprecated; the Kanban Engine remains as internal
  API for flow enforcement and TDD gate validation.

## [0.9.2] - 2026-08-08

### Added

- **Single execution contract** — `AgentTask` (input), `AgentResult` (output),
  `AgentError` (standardized error with stable codes:
  `VALIDATION_ERROR`, `RUNTIME_ERROR`, `PERMISSION_DENIED`, `TIMEOUT`,
  `CANCELLED`, `UNKNOWN`), `AgentCapabilities`, and `AgentMetadata` (name,
  version, timeout, retry policy). Every agent implements
  `execute(task, context) -> AgentResult`. (#6)
- **AgentExecutor as the single execution boundary** — validates the task,
  enforces capabilities (`PERMISSION_DENIED`), drives the lifecycle, and
  applies timeout, retry (transient errors only, default **no retry**), and
  cancellation centrally. Invokes `agent.execute()`; agents are executor-free,
  so recursion is structurally impossible. (#6)
- **Standardized lifecycle** — `created → validated → queued → running →
  succeeded | failed | timed_out | cancelled`, with immutable terminal states
  and timestamps/duration exposed on the result and the event bus. `running →
  running` marks a retry. The `created → created` event is the initialization
  event (not a transition) and guarantees every execution has a complete,
  deterministic sequence. (#6)
- **Two-tier lifecycle/execution events** — `agent.lifecycle.changed` (every
  state transition, with `previous_state`/`current_state`) plus
  `agent.execution.started/progress/completed/failed/timed_out/retried/
  cancelled`. Every event shares a consistent payload: `event_id`, `agent`,
  `task_id`, `correlation_id`, `executor_id` (per instance), `sequence` (per
  execution), `attempt`, `status`, `duration_ms`, `error_code`, `message`.
  The legacy `agent.execution.finished` topic was removed. (#6)
- **Capability enforcement** — `CapabilityEnforcer` validates declared
  capabilities against the canonical policy and guards read-only agents
  (Planner/Research/Reviewer) from write/shell/internet. The executor applies
  it before running; violations map to `PERMISSION_DENIED`. (#6)
- **Compliance matrix** — `tests/agent_compliance_matrix.py` declares, per
  agent, the input/output contract, capabilities, timeout, retry policy,
  required events, and error behavior. Contract, integration, and architecture
  tests are driven by it. (#6)
- **Test suites** — per-agent contract tests, integration tests via the
  executor (all 7 agents, events, retry, capability enforcement), and
  architecture checks enforcing both directions of the execution boundary and
  the single producer of `agent.*` events. (#6)
- **Workflow/CLI full compliance** — `WorkflowEngine`, `Kernel.run()`, and the
  `review`/`research` CLI commands route exclusively through the executor /
  `Kernel.run_agent()`. Rich domain APIs (`review`, `research`, `run`,
  `generate_changelog_fragment`, git ops) became private implementations. (#6)
- **Report** — `docs/reports/agent-core-compliance-report.md` with per-agent
  ✅/❌ verdicts per category.

### Changed

- `ReviewerAgent`, `ResearchAgent`, `TesterAgent`, `DocumentationAgent`, and
  `GitAgent` now expose `execute(task, context)` as their contract method and
  route all work through the AgentExecutor; their deterministic domain methods
  are private.
- Planner/Developer runtime errors now propagate so the AgentExecutor can
  retry transient failures centrally; domain failures (e.g., invalid JSON
  plans) still return a failed `AgentResult`.
- The `aios/policies/agent_capabilities.yaml` reference policy now covers all
  seven agents consistently.

## [0.9.1] - 2026-08-08

### Added

- **Researcher (first-class agent)** — `ResearchAgent` upgraded from a
  fetcher-only scaffold into a contract-bound researcher. Input is a
  `ResearchTask`; output is a validated `ResearchResult` with `sources`,
  `findings` (provenance via `evidence_source_ids`), `confidence_overall`,
  `recommendations`, and advisory `memory_candidates`. (#15)
- **Research domain contracts** — `aios.research` package with dataclasses
  (`ResearchTask`, `ResearchSource`, `Finding`, `Recommendation`,
  `MemoryCandidate`, `ResearchResult`) and schema validation enforcing
  traceability, unique ids, bounded confidence, and a 140-char summary.
- **Deterministic local collection** — `repo`/`docs` scopes are collected
  locally with `filesystem_read` only (zero-dependency, keyword scan).
- **Explicit availability status** — `web` scope without an injected fetcher
  returns `status="source_unavailable"` with no fabricated claims; `mixed`
  degrades gracefully to `status="partial"`.
- **Optional workflow front-gate** — `WorkflowEngine` accepts an optional
  `researcher`; when injected, research runs before the planner and its
  result feeds downstream agents via `ContextPacket.research`. When absent,
  the pipeline is unchanged.
- **CLI** — `aios research "<question>" [--scope repo|docs|web|mixed]
  [--json] [--output FILE]`.

### Changed

- `ResearchAgent.required_capabilities` is now `["filesystem_read"]` only.
  Internet access is a contextual capability of an injected web source
  fetcher, not a hard prerequisite of the agent.

### Notes

- `memory_candidates` are advisory output only. This version never persists
  candidates into the Memory Engine; a future admission mechanism decides
  what becomes project knowledge.
- No web provider ships in core. Web research requires injecting a fetcher
  (`Callable[[ResearchTask], list[ResearchSource]]`), keeping the core
  zero-dependency and local-first.

[Unreleased]: https://github.com/GabrielPabloG/aiosdeck/compare/v0.9.1...main
[0.9.1]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.1
[0.9.0]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.0

## [0.9.0] - 2026-08-06

Milestone release capturing the implemented work since v0.1.0. Workflows,
Plugins, and the Tester/Documentation/Git/Research agents remain **Specified** —
they are planned, not yet shipped.

### Added

- **Planner (v0.6)** — goal decomposition into ordered subtasks with priorities,
  dependencies, risks, and unknowns. Reasoning loop (max 3 iterations) with
  `ask_user` tool execution and JSON self-healing. (#4)
- **Reviewer (v0.7)** — read-only code/architecture evaluator returning a strict
  JSON verdict. Shipped as a tested component **without CLI integration**; the
  `aios review` command is future work. (#5)
- **Scheduler (v0.8)** — persistent kanban/scrum boards with SQLite storage,
  card/subtask lifecycle, TDD gate enforcement, and project isolation. (#6)
- **Reactive live board** — event-driven kanban rendering during `plan --run`
  execution, with blocked-card notifications. (#9, #10)
- **AgentExecutor** — generic execution guardrail (timeout, retry, event bus
  publishing) shared by all agents. (#3)
- **OpenCode runtime** — headless `opencode run --auto` invocation with
  capability-based permission enforcement and ai-jail sandbox. (#2, #1)
- **CLI** — `aios init`, `aios doctor --json`, Command Registry as single source
  of truth, bash/zsh completion, and the `ad` alias. (#5)
- **Memory Engine (v0.3)** — SQLite-backed conventions, decisions, patterns, and
  mistakes, stored in `.aios/memory.db`. (#1)

### Changed

- `aios plan <intent> --run` now creates a sprint board, populates the initial
  backlog, and blocks cards when the TDD gate fails (fail-fast). (#10)
- Project state moved to `.aios/memory.db`; the project manifest lives in
  `.aios/project.yaml`.
- Graceful shutdown on SIGINT/SIGTERM.

### Fixed

- CI resilience when OpenCode/ai-jail are not installed on runners.
- Console spinner cleanup and ANSI line handling to prevent vertical wrapping. (#8)
- Runtime timeouts tuned for long planning/execution sessions.

### Security

- Headless tool permissions are enforced in the RuntimeAdapter (`OPENCODE_PERMISSION`).
- OpenCode is always invoked through the ai-jail sandbox, never directly.

### Notes

- Reviewer is a tested component but is **not** exposed via the CLI or kernel yet.
- Workflows, the Plugin System, and the v0.9 agents (Tester, Documentation, Git,
  Research) are documented under `docs/` but **not implemented** in this release.
- Requires Python 3.12+. Status: **Alpha**.

[Unreleased]: https://github.com/GabrielPabloG/aiosdeck/compare/v0.9.0...main
[0.9.0]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.0
