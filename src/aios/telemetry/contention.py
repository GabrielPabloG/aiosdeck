"""Deterministic lock-contention micro-benchmark for telemetry (Issue #70).

Measures the cost of concurrent ``TelemetryStore.insert_execution`` — the
synchronous pre-batch write path, one BEGIN/COMMIT per event — across three
connection strategies against temp-file SQLite DBs with zero model or network:

- ``shared_n_threads``      — N threads, one connection/one DB. The single
  ``ThreadSafeConnection.RLock`` serializes every write (Amdahl bound).
- ``independent_n_threads`` — N threads, N connections each in its own DB file.
  A true parallel baseline: distinct connections to distinct files never share
  a WAL, so the only serialization left is the interpreter/GIL.
- ``flush_concurrent``      — N threads enqueue into one ``TelemetryWriter``
  (O(1) path) whose background worker flushes the shared DB in batched
  ``atomic()`` transactions.

Methodology (measure, not a lifecycle report):

- ``warmup`` ops per thread run untimed; then all threads cross a
  ``threading.Barrier`` and the ``ops_per_thread`` measured ops run together.
  Import/JIT/startup noise is absorbed by warmup, and the barrier gates the
  measured phase so threads start together.
- Determinism: deterministic record per ``(thread, index)`` (unique
  ``event_id``), ``PYTHONHASHSEED=0`` and single-threaded BLAS env vars
  (``OMP_NUM_THREADS``/``MKL_NUM_THREADS``) applied by the CLI wrapper, and
  ``time.perf_counter_ns`` per op.
- Per-op latency is collected in microseconds via
  :func:`aios.telemetry.benchmark.summarize`; throughput is total measured ops
  over the wall time of the gated measured phase (barrier release → last op).

Structural invariant (CI-safe, not a % threshold): the only timing claim we
assert is accuracy under threading — every concurrent op must be persisted (no
loss) with non-negative latency. We deliberately do NOT assert a directional
ordering of shared-vs-independent throughput/latency: independent multi-file
SQLite is dominated by per-file WAL fsync contention on a shared disk and can
measure *slower* than one serialized connection at N≥4, inverting naive Amdahl
intuition. The ``degradation`` block records the measured ratios without
asserting any bound.

This is intentionally a standalone instrument: it does NOT write a lifecycle
report, so the closed ``GROUPS``/``METRICS`` schema in ``schema.py`` stays
untouched (no bump). Metadata/provenance is assembled here (``system_info``
from ``schema.py`` + ``sqlite3.sqlite_version``).
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from aios.telemetry.benchmark import summarize
from aios.telemetry.schema import system_info
from aios.telemetry.store import TelemetryStore
from aios.telemetry.writer import TelemetryWriter

TABLE = "executions"
DEFAULT_BATCH_SIZE = 50
LATENCY_KEYS = ("p50", "p95", "p99")


def _record(prefix: str, thread: int, index: int) -> dict:
    """One deterministic execution record, unique per (thread, index)."""
    return {
        "execution_id": f"{prefix}-{thread}-{index:06d}",
        "event_id": f"{prefix}-{thread}-{index:06d}",
        "agent": "contention-bench",
        "model": "none",
        "status": "ok",
        "duration_ms": 1.0,
    }


def _measure(
    worker,
    threads: int,
    ops_per_thread: int,
    warmup: int,
) -> tuple[list[float], int]:
    """Run *worker* on *threads* threads: warmup untimed, then measured across
    a barrier. Returns per-op latencies (µs) and the wall time (ns) of the
    gated measured phase (min start → max end across threads)."""
    start_barrier = threading.Barrier(threads)
    per_thread: list[list[float]] = [[] for _ in range(threads)]
    start_times = [0] * threads
    end_times = [0] * threads

    def run_one(tid: int) -> None:
        for i in range(warmup):
            worker(tid, i)
        start_barrier.wait()
        start_times[tid] = time.perf_counter_ns()
        local: list[float] = []
        for i in range(ops_per_thread):
            t0 = time.perf_counter_ns()
            worker(tid, warmup + i)
            local.append((time.perf_counter_ns() - t0) / 1000.0)
        per_thread[tid] = local
        end_times[tid] = time.perf_counter_ns()

    ts = [threading.Thread(target=run_one, args=(i,)) for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    samples = [s for tl in per_thread for s in tl]
    wall_ns = max(end_times) - min(start_times)
    return samples, wall_ns


def _scenario(
    samples: list[float],
    wall_ns: int,
    total_ops: int,
    **extra,
) -> dict:
    summary = summarize(samples)
    throughput = (total_ops / (wall_ns / 1e9)) if wall_ns else 0.0
    return {
        "throughput_ops_s": round(throughput, 1),
        "latency_us": {k: round(summary[k], 2) for k in LATENCY_KEYS},
        **extra,
    }


def _count_rows(db_path: Path) -> int:
    """Row count in the executions table via an independent reader connection."""
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM telemetry_executions").fetchone()[0])
    finally:
        conn.close()


def measure_shared(tmp: Path, threads: int, ops_per_thread: int, warmup: int) -> dict:
    """One connection, one DB: N threads share a single serialized connection."""
    db = tmp / "contention-shared.db"
    store = TelemetryStore(db, "contention-shared")
    store.open()
    try:

        def worker(tid: int, index: int) -> None:
            store.insert_execution(_record("shared", tid, index))

        samples, wall_ns = _measure(worker, threads, ops_per_thread, warmup)
    finally:
        store.close()
    persisted = _count_rows(db)
    return _scenario(
        samples,
        wall_ns,
        threads * ops_per_thread,
        persisted=persisted,
    )


def measure_independent(tmp: Path, threads: int, ops_per_thread: int, warmup: int) -> dict:
    """N connections, N DB files: a true parallel baseline (no shared WAL)."""
    stores = []
    for tid in range(threads):
        store = TelemetryStore(tmp / f"contention-ind-{tid}.db", "contention-independent")
        store.open()
        stores.append(store)
    try:

        def worker(tid: int, index: int) -> None:
            stores[tid].insert_execution(_record("independent", tid, index))

        samples, wall_ns = _measure(worker, threads, ops_per_thread, warmup)
    finally:
        for store in stores:
            store.close()
    persisted = sum(_count_rows(tmp / f"contention-ind-{tid}.db") for tid in range(threads))
    return _scenario(
        samples,
        wall_ns,
        threads * ops_per_thread,
        persisted=persisted,
    )


def measure_flush(
    tmp: Path,
    threads: int,
    ops_per_thread: int,
    warmup: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    """N threads enqueue into one writer; the background worker flushes the
    shared DB in batched atomic() transactions."""
    db = tmp / "contention-flush.db"
    store = TelemetryStore(db, "contention-flush")
    store.open()
    writer = TelemetryWriter(store, batch_size=batch_size)
    try:

        def worker(tid: int, index: int) -> None:
            writer.enqueue(TABLE, _record("flush", tid, index))

        samples, wall_ns = _measure(worker, threads, ops_per_thread, warmup)
    finally:
        writer.shutdown()
        metrics = writer.metrics()
        store.close()
    persisted = _count_rows(db)
    return _scenario(
        samples,
        wall_ns,
        threads * ops_per_thread,
        flushes_observed=metrics["flush_count"],
        events_dropped=metrics["events_dropped_total"],
        events_flushed_total=metrics["events_flushed_total"],
        persisted=persisted,
    )


def run_contention(
    base: Path,
    *,
    threads: int = 4,
    ops_per_thread: int = 1000,
    warmup: int = 50,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    """Measure all three scenarios on temp-file DBs and build the standalone
    report: scenarios + measured degradation, plus provenance metadata. No
    lifecycle report is written (schema untouched); ``model`` is ``None`` and
    ``network`` is ``False`` by construction."""
    with tempfile.TemporaryDirectory(prefix="contention-", dir=str(base)) as dirname:
        tmp = Path(dirname)
        shared = measure_shared(tmp, threads, ops_per_thread, warmup)
        independent = measure_independent(tmp, threads, ops_per_thread, warmup)
        flush = measure_flush(tmp, threads, ops_per_thread, warmup, batch_size=batch_size)

    def degradation() -> dict:
        return {
            "shared_vs_independent": {
                k: shared["latency_us"][k] / independent["latency_us"][k] for k in LATENCY_KEYS
            }
        }

    return {
        "model": None,
        "network": False,
        "metadata": {
            "system_info": system_info(),
            "sqlite_version": sqlite3.sqlite_version,
            "threads": threads,
            "ops_per_thread": ops_per_thread,
            "warmup": warmup,
            "measured": threads * ops_per_thread,
        },
        "scenarios": {
            "shared_n_threads": shared,
            "independent_n_threads": independent,
            "flush_concurrent": flush,
        },
        "degradation": degradation(),
    }
