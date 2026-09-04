# RC/GA Checklist — v1.0.0

**Status**: GA Confirmed (2026-08-10)
**Date**: 2026-08-09

This checklist gates the v1.0.0 release candidate. Every item must pass before
tagging `v1.0.0-rc1`; the GA (`v1.0.0`) adds only the release/regression gates.

## v1.1.1 — Infrastructure Stability & Benchmark Suite

**Status**: Confirmed (2026-09-03)
**Scope**: manifest-configurable routing fallbacks (#82), sandboxed
OllamaAdapter + provider config + preflight diagnostics (#66/#80/#81),
benchmark compare gate (#72) and telemetry microbenchmarks (#69/#71),
buffered telemetry writer (#65), ConnectionPool (#64), persistent thread
pool (#73), shared event loop (#74), workflow no-op gate (#90), runtime
agent selection fix (#83), PyYAML loud failure (#93), fair mutation-score
CI gate (#145).

Automated gates (all green at release time, on `main`):

- [x] `pytest tests/ -q` — full suite green, 0 failures.
- [x] `ruff check src/ tests/` — zero errors.
- [x] `ruff format --check src/ tests/` — zero reformatting.
- [x] Version consistency — `pyproject.toml` = `aios.__version__` = `1.1.1`.
- [x] Official baseline `v1.1.1.json` validated (`aios benchmark validate`);
      first bare baseline `v1.1.1-bare.json` captured on the same commit
      (plan p50 14.9 s full vs 5.2 s bare — orchestration overhead).
- [x] `v1.1.1-qwen-local.json` kept as a non-official hardware stress record.
- [x] `docs/CHANGELOG.md` `[1.1.1]` section matches the released notes.
- [ ] Tag `v1.1.1` (annotated) on `main`; push triggers the CD pipeline
      (gates → build → `twine check` → PyPI → GitHub Release).

## v1.1.0 — Benchmark Instrumentation Milestone

**Status**: Prepared (2026-08-12) — tag `v1.1.0` pending
**Scope**: `aios benchmark` CLI + versioned schema v1.1, startup profiling
hooks (#37), bare task mode (#51), routing parity (#63), progress feedback,
deepseek v4 flash pricing.

Automated gates (all green at preparation time, on `main`):

- [x] `pytest tests/ -q` — 1455 tests, 0 failures.
- [x] `ruff check src/ tests/` — zero errors.
- [x] `ruff format --check src/ tests/` — zero reformatting.
- [x] Version consistency — `pyproject.toml` = `aios.__version__` = `1.1.0`.
- [x] Baseline `v1.0.0` still validated (`aios benchmark validate`).
- [x] `docs/CHANGELOG.md` `[1.1.0]` section matches the released notes.
- [ ] Tag `v1.1.0` (annotated) on `main`; push triggers the CD pipeline
      (gates → build → `twine check` → PyPI → GitHub Release).

## S5.1 — Technical RC Checklist

Run on the `feature/stable-1.0` branch.

- [x] `pytest tests/ -q` — full suite green (1358 tests, 0 failures).
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
- [x] `aios --version` reports `1.0.0`.

## S5.2 — CLI UX Checklist

Manual verification on a throwaway project (see `docs/fire-test.md`).

- [x] `aios ocean` renders the overview without error (TTY and non-TTY).
- [x] `aios ocean --once` and `aios ocean --json` produce correct output.
- [x] `aios help` lists all top-level commands; no traceback.
- [x] `aios` bare invocation shows the dashboard without crash.
- [x] `aios completion --bash` / `--zsh` produce valid scripts.
- [x] `aios doctor` reports a healthy kernel (or clear warnings).
- [x] `aios plan <intent>` (plan mode) works end-to-end.
- [x] `aios review`, `aios research`, `aios memory`, `aios knowledge`,
      `aios skills`, `aios learning`, `aios route`, `aios usage` all respond
      without traceback.
- [x] Unknown command / bad option → formatted error, exit code 1, no traceback.

## S5.3 — Telemetry Minimums

Fire test (`docs/fire-test.md`) validates on a real run:

- [x] `telemetry_executions` has ≥1 row (84 rows in the fire test).
- [x] `telemetry_routing` has ≥1 row (6 rows in the fire test).
- [~] `telemetry_costs` has ≥1 row (when the provider reports usage). — Not
      exercised in the fire test: the local run deferred token tracking, so
      `telemetry_usage`/`telemetry_costs` stayed at 0 by design (see Known
      Limitations in `docs/fire-test.md`).
- [x] `agent.lifecycle.changed` + `agent.execution.*` events evidenced in
      `telemetry_executions` (`created/queued/running/validated/succeeded`).
- [x] `aios usage` shows data (executions; honest "token tracking deferred"
      note when the provider reports no usage).

## S5.4 — Regression Gates (for GA)

- [x] All release-notes content matches `docs/CHANGELOG.md` [1.0.0].
- [x] Docs status blocks reflect Implemented/Partial/Planned truthfully.
- [x] `docs/migration-1.0.md` reflects the actual diff from v0.9.x.
- [x] GA `v1.0.0` tagged (annotated, force-moved) on `feature/stable-1.0`
      after the regression/fire-test run.

## Release Procedure

1. Run S5.1 (automated) — must be green.
2. Run S5.2 + S5.3 (manual, on a throwaway repo) — must pass.
3. Bump `__version__` and `pyproject.toml` to the target version.
4. Tag `v<version>` (annotated) on the release branch.
5. Push the tag — the CD pipeline (`.github/workflows/release.yml`) runs
   gates → build → `twine check` → PyPI (Trusted Publishing, no token) →
   GitHub Release with `dist/` artifacts and CHANGELOG notes.

The pipeline can be exercised without publishing via the `release.yml`
`workflow_dispatch` inputs: `dry-run` (validate gates + build + package,
no publish) or `testpypi` (publish to TestPyPI). A version mismatch between
the tag, `pyproject.toml`, and `aios.__version__` fails the gate and blocks
the release.

**GA notes (2026-08-10):** the stabilization branch went straight to `v1.0.0`
without a separate `v1.0.0-rc1` tag. The GA tag points to the final HEAD after
the fire-test regression run (S5.1–S5.3 above). Publishing v1.0.0 is automated:
`git push origin v1.0.0` triggers the CD pipeline.
