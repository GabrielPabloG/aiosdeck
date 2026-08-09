# RC/GA Checklist — v1.0.0

**Status**: Planned (run before tagging v1.0.0-rc1)
**Date**: 2026-08-09

This checklist gates the v1.0.0 release candidate. Every item must pass before
tagging `v1.0.0-rc1`; the GA (`v1.0.0`) adds only the release/regression gates.

## S5.1 — Technical RC Checklist

Run on the `feature/stable-1.0` branch.

- [ ] `pytest tests/ -q` — full suite green (1300+ tests, target 0 failures).
- [ ] `ruff check src tests` — zero errors.
- [ ] `ruff format --check src tests` — zero reformatting.
- [ ] No new runtime dependencies (stdlib + existing only).
- [ ] No module exceeds an accepted size; large modules documented
      (`telemetry/store.py` single-responsibility note).
- [ ] No circular imports: fresh interpreter imports `aios.cli.commands`,
      `aios.agents.executor`, `aios.security.intent_validator`.
- [ ] Contract tests (`tests/contracts/`) all pass — frozen signatures intact.
- [ ] Architecture tests (`tests/architecture/`) all pass — executor-free agents,
      single event producer, no rich-domain-API bypass.
- [ ] `aios --version` reports `1.0.0-rc1` (or the intended tag version).

## S5.2 — CLI UX Checklist

Manual verification on a throwaway project (see `docs/fire-test.md`).

- [ ] `aios ocean` renders the overview without error (TTY and non-TTY).
- [ ] `aios ocean --once` and `aios ocean --json` produce correct output.
- [ ] `aios help` lists all 20 top-level commands; no traceback.
- [ ] `aios` bare invocation shows the dashboard without crash.
- [ ] `aios completion --bash` / `--zsh` produce valid scripts.
- [ ] `aios doctor` reports a healthy kernel (or clear warnings).
- [ ] `aios plan <intent>` (plan mode) works end-to-end.
- [ ] `aios review`, `aios research`, `aios memory`, `aios knowledge`,
      `aios skills`, `aios learning`, `aios route`, `aios usage` all respond
      without traceback.
- [ ] Unknown command / bad option → formatted error, exit code 1, no traceback.

## S5.3 — Telemetry Minimums

Fire test (`docs/fire-test.md`) validates on a real run:

- [ ] `telemetry_executions` has ≥1 row.
- [ ] `telemetry_tokens` has ≥1 row.
- [ ] `telemetry_costs` has ≥1 row.
- [ ] `agent.lifecycle.changed` + `agent.execution.*` events published.
- [ ] `aios usage` shows data.

## S5.4 — Regression Gates (for GA)

- [ ] All release-notes content matches `docs/CHANGELOG.md` [Unreleased].
- [ ] Docs status blocks reflect Implemented/Partial/Planned truthfully.
- [ ] `docs/migration-1.0.md` reflects the actual diff from v0.9.x.
- [ ] Tag `v1.0.0-rc1` on `feature/stable-1.0` after S5.1–S5.3 pass.
- [ ] GA `v1.0.0` tagged from the same state after regression run.

## Release Procedure

1. Run S5.1 (automated) — must be green.
2. Run S5.2 + S5.3 (manual, on a throwaway repo) — must pass.
3. Bump `__version__` and `pyproject.toml` to `1.0.0-rc1`.
4. Tag `v1.0.0-rc1`.
5. After the RC soak (regression run), tag `v1.0.0` from the same commit.
