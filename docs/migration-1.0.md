# Migration Guide — 0.9.x → 1.0

**Status**: Implemented
**Review date**: 2026-08-09
**Date**: 2026-08-09

This guide covers everything a user or contributor needs to move from the
v0.9.x line to v1.0. v1.0 is a **stabilization release**: the public surface
(CLI commands, agent contracts, telemetry tables, event topics) is frozen and
documented. There are no intentional breaking changes to user workflows.

## Summary

| Area | Breaking? | Notes |
|------|-----------|-------|
| CLI commands | No | Same top-level commands, same flags |
| Agent contracts | No | `AgentTask` / `AgentResult` / `AgentError` frozen |
| Security intents | No | `IntentPolicy` / `EffectivePermissions` frozen |
| Telemetry tables | No | 9 tables unchanged; schema additive only |
| Event topics | No | `ALL_TOPICS` unchanged |
| Python API | No | Public exports stable via `__init__.py` |
| Internal layout | Yes (contributors) | CLI moved into `cli/commands/` package |

## Upgrading

```bash
pip install -U aiosdeck
```

No config migration is required. Existing `~/.config/aiosdeck/config.yaml`
files and `.aios/memory.db` databases continue to work unchanged.

## What Changed

### v1.0 Stabilization (this branch)

- **Contracts frozen** — agent input/output/error contracts are covered by
  contract tests (`tests/contracts/`). Changing a frozen signature now requires
  a version bump.
- **Security intent enforcement** — the allow/deny decision logic moved into
  `aios.security.intent_validator` (`validate_intent`). Behavior is unchanged;
  the decision point is now auditable and unit-tested in isolation.
- **Dead code removed** — `routing/ranker.py` (HeuristicRanker/TelemetryRanker)
  was removed. `RuleBasedRouter` is the only v1.0 routing implementation.
- **Skills dedup** — skill discovery is single-sourced in `SkillRegistry`;
  `format_skill_header()` is shared between retrieval and prompt building.
  Output is byte-identical.
- **CLI restructured (contributors)** — `src/aios/cli/commands.py` became the
  `src/aios/cli/commands/` package:
  - `cli/commands/__init__.py` — central registry (`COMMANDS` dict)
  - `cli/commands/core.py` — dashboard, doctor, init, help, exit, complete
  - `cli/commands/exec_cmds.py` — plan, research, review
  - `cli/commands/memory.py` — memory add/list/forget/search
  The command surface (`aios plan`, `aios review`, ...) is unchanged.

### From earlier 0.9.x releases (for reference)

- v0.9.13 — Backlog Runner (`aios backlog run/list/add/stats`).
- v0.9.12 — Ocean Console (`aios ocean`).
- v0.9.11 — Model Router (`aios route`); the ranker interface became internal.
- v0.9.10 — Learning Governance (`aios learning`).
- v0.9.2 — Single execution contract: every agent exposes
  `execute(task, context) -> AgentResult`; the legacy
  `agent.execution.finished` topic was removed.

## Rollback

v1.0 writes the same `.aios/memory.db` schema as v0.9.13 (additive only), so
downgrading from v1.0 back to v0.9.13 is safe. Telemetry tables created in v1.0
do not add columns to existing tables.

## Post-1.0 Labels

The following were explicitly **not** included in v1.0 and remain post-1.0:

| Feature | Status |
|---------|--------|
| Auto-optimization of learning | Beta-flag / deferred |
| TelemetryRanker | Removed (stub contract only) |
| Advanced widgets / forms | Deferred |
| Plugin system | Planned |
| Concurrent execution queue | Deferred |
| Desktop / web integrations | Deferred |
| Real cost tracking (`route_accuracy` via opencode `--format json` parse) | Deferred |
