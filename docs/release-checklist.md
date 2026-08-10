# RC/GA Checklist — v1.0.0

**Status**: Verified (2026-08-10)
**Date**: 2026-08-09

This checklist gates the v1.0.0 release candidate. Every item must pass before
tagging `v1.0.0-rc1`; the GA (`v1.0.0`) adds only the release/regression gates.

## S5.1 — Technical RC Checklist

Run on the `feature/stable-1.0` branch.

- [x] `pytest tests/ -q` — full suite green (1344 tests, 0 failures).
- [x] `ruff check src tests` — zero errors.
- [x] `ruff format --check src tests` — zero reformatting.
- [x] No new runtime dependencies (stdlib + existing only).
- [x] No module exceeds an accepted size; large modules documented
      (`telemetry/store.py` single-responsibility note).
- [x] No circular imports: fresh interpreter imports `aios.cli.commands`,
      `aios.agents.executor`, `aios.security.intent_validator`.
- [x] Contract tests (`tests/contracts/`) all pass — frozen signatures intact
      (148 passed).
- [x] Architecture tests (`tests/architecture/`) all pass — executor-free agents,
      single event producer, no rich-domain-API bypass (8 passed).
- [x] `aios --version` reports `1.0.0-rc1` (or the intended tag version).

## S5.2 — CLI UX Checklist

Manual verification on a throwaway project (see `docs/fire-test.md`).

- [ ] `aios ocean` renders the overview without error (TTY and non-TTY).
- [ ] `aios ocean --once` and `aios ocean --json` produce correct output.
- [ ] `aios help` lists all top-level commands; no traceback.
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
- [ ] `telemetry_routing` has ≥1 row.
- [ ] `telemetry_costs` has ≥1 row (when the provider reports usage).
- [ ] `agent.lifecycle.changed` + `agent.execution.*` events evidenced in
      `telemetry_executions`.
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
