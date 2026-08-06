# Changelog

All notable changes to AiosDeck are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
