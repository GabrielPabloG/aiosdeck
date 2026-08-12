# Benchmark Schema (v1.1)

**Status**: Accepted
**Date**: 2026-08-11 (v1.0) / 2026-08-12 (v1.1)

## Context

`aios benchmark` produces performance baselines that feed CI regression gates,
per-version history, and text/JSON consumers. Those artifacts must be
machine-checkable and stable across versions. The schema versioned here is the
contract every benchmark report must satisfy.

v1.1 keeps the envelope and `results[]` shape of v1.0 (1.0 reports remain
valid) and adds two optional features: a per-run `timings` breakdown and
**benchmark modes** — bare vs full — expressed as metadata, never as new
metrics.

## The canonical representation

**`results[]` is the only canonical representation of benchmark output.** The
full pipeline is:

```
measurement → Result → results[] → text|JSON → baseline/history → CI budgets
```

Every measurement (a lifecycle phase, a CLI command, a startup probe) becomes
one flat entry in `results[]`. No parallel `phases`/`commands`/`startup`
structures survive at the top level of a report — the schema validator rejects
nothing for *extra* keys, but the CLI never emits them, and consumers must walk
`results[]`.

## Envelope

A valid report is a single JSON object with these required top-level keys:

| Key | Type | Meaning |
|-----|------|---------|
| `schema_version` | string | Schema version this report conforms to (`"1.1"`; `"1.0"` still accepted) |
| `aiosdeck_version` | string | AiosDeck version that produced the report |
| `git_commit` | string | Short HEAD commit hash (`"unknown"` if git unavailable) |
| `timestamp` | string | ISO-8601 UTC timestamp |
| `system_info` | object | Platform snapshot (system, platform, machine, processor, python) |
| `results` | array | Flat list of measured results |

Optional metadata (`warmup`, `repeat`, `skip_agents`, `output`,
`benchmark_mode`, `task_prompt_type`, `runtime_info`) is allowed and used for
reproducibility, but it is not part of the contract.

## Benchmark modes

Every report describes *how* the LLM work was measured. The mode is **metadata
on the envelope**, never a new metric — latency stays `wall_time_ms`.

| Envelope key | Values | Meaning |
|--------------|--------|---------|
| `benchmark_mode` | `"full"` \| `"bare"` | `"full"`: agents run the real task; `"bare"`: `plan`/`agent_exec` are a restricted runtime probe |
| `task_prompt_type` | `"full_task"` \| `"restricted_ok"` | What prompt reached the model: the full task prompt vs. the fixed bare probe |

In `bare` mode the `plan` and `agent_exec` results carry result-level metadata
(extras at the result level, not inside `runs`):

| Result key | Type | Meaning |
|------------|------|---------|
| `tool_calls_count` | integer | `0` by construction — empty permissions deny every tool |
| `is_read_only` | boolean | `true` by construction — no write/shell/git/network grants |

A bare probe whose reply is not "OK"-shaped records a `warnings` list on the
result (tolerant check); it never fails the run, because the zero-trust
guarantee comes from the empty permissions, not from the reply text.

## Result entries

Each element of `results[]` carries `group` (one of `phases`, `commands`,
`startup`) and `target` (the measured unit: a phase name, a command name, or
`"startup"`). A result is either **measured** or **skipped**:

### Measured

```json
{
  "group": "commands",
  "target": "doctor",
  "runs": [
    {
      "wall_time_ms": 68.65,
      "cpu_user_ms": 10.0,
      "cpu_system_ms": 0.0,
      "peak_memory_kb": 44120.0
    }
  ],
  "summaries": {
    "wall_time_ms": { "count": 1, "min": 68.65, "max": 68.65,
                      "mean": 68.65, "p50": 68.65, "p95": 68.65,
                      "p99": 68.65, "samples": [68.65] }
  }
}
```

`runs` preserves each raw sample in order; `summaries` holds per-metric
statistics (count/min/max/mean/p50/p95/p99/samples). A run may carry an
optional `error` string — failed measurements still record their duration —
and, since v1.1, an optional `timings` object (`kernel.timings` breakdown,
emitted by `--profile`).

### Skipped

```json
{
  "group": "commands",
  "target": "plan",
  "skipped": true,
  "reason": "requires agent runtime (--skip-agents)"
}
```

Skipped is explicit — it never looks like "0 ms".

## Metrics

The per-run metric set is **closed**: exactly these four keys, plus the
optional `error` (string) and, since v1.1, `timings` (object).

| Metric | Unit | Source |
|--------|------|--------|
| `wall_time_ms` | milliseconds | `time.monotonic()` delta |
| `cpu_user_ms` | milliseconds | `os.times().user` delta |
| `cpu_system_ms` | milliseconds | `os.times().system` delta |
| `peak_memory_kb` | kilobytes | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |

Anything descriptive about a run (mode, read-onlyness, tool-call counts,
warnings) lives at the **result level**, which accepts extra keys — never
inside a run, where unknown keys are rejected.

### `peak_memory_kb` semantics

`ru_maxrss` is normalized to **kilobytes** by a platform adapter: Linux returns
KB directly; macOS returns bytes and is divided by 1024. The value is the
process peak RSS *at the moment the run was sampled*, so it is monotonic within
a single benchmark process. A run that could not execute records `0.0` (present
but zero) so the metric always exists.

## Validation

`aios benchmark validate <file>` checks a report against the schema and exits
`0` (valid) or `1` (invalid), printing each violation. The validator is
hand-rolled and zero-dependency (`src/aios/telemetry/schema.py`):

```python
from aios.telemetry.schema import validate_report
errors = validate_report(report)  # [] == valid
```

It enforces: all required top-level keys present, `schema_version` matches,
`results` is a list, each result has a known `group` and a `target`, skipped
results carry a `reason`, and measured results have a non-empty `runs` list
whose metrics are exactly the four above (unknown keys inside a run are
rejected). Result-level extra keys (`tool_calls_count`, `is_read_only`,
`warnings`, ...) and envelope metadata (`benchmark_mode`, `task_prompt_type`)
are accepted.

## Hyperfine mapping

[hyperfine](https://github.com/sharkdp/hyperfine) reports
`mean ± std`, `median`, `min`, `max`, and per-run times. The mapping to this
schema:

| hyperfine | schema |
|-----------|--------|
| one hyperfine run (command under test) | one `results[]` entry (`group` = `commands`, `target` = command name) |
| `--warmup N` | `warmup` envelope key; warmup runs are discarded |
| `--runs N` | `repeat` envelope key; length of `runs` |
| per-run `times[i]` | `runs[i].wall_time_ms` (no external command needed) |
| `min` / `median` / `mean` | `summaries.<metric>.min` / `p50` / `mean` |
| `--export-json` output | the full report envelope + `results[]` |
| skipped agent targets | `skipped: true` + `reason` (hyperfine has no equivalent) |

Unlike hyperfine, AiosDeck measures CPU time and peak memory per run, in the
same process that produced the report, with no external binary dependency.
