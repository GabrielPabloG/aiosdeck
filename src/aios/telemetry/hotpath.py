"""Deterministic micro-benchmark of the telemetry write hot path (Issue #67).

Measures the three write paths in microseconds per event, all against the
same SQLite temp-file DB + WAL and the same record shape, with zero model or
network involvement:

- ``enqueue``  — ``TelemetryWriter.enqueue`` (the O(1) hot path), timed with
  the background flush thread parked so the worker cannot contend for the
  buffer lock and corrupt the measurement.
- ``sync``     — ``TelemetryStore._insert_one``, the pre-batching write path
  that opens one transaction per event.
- ``batch``    — amortized ``TelemetryStore.insert_many`` inside a single
  ``store.atomic()`` transaction, divided by ``batch_size`` to give cost per
  event.

This is intentionally a standalone instrument: it does NOT write a lifecycle
report, so the closed ``GROUPS``/``METRICS`` schema in ``schema.py`` stays
untouched (no bump). Summary statistics reuse :func:`aios.telemetry.benchmark.
summarize` rather than reimplementing percentile math.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from aios.telemetry.benchmark import summarize
from aios.telemetry.store import TelemetryStore
from aios.telemetry.writer import TelemetryWriter

DEFAULT_TABLE = "executions"
DEFAULT_BATCH_SIZE = 50
DEFAULT_ENQUEUE_EVENTS = 20_000
DEFAULT_SYNC_EVENTS = 300
DEFAULT_BATCH_BLOCKS = 50


def record(prefix: str, index: int) -> dict:
    """One deterministic ``executions`` record shaped identically per path."""
    return {
        "execution_id": f"{prefix}-{index:06d}",
        "event_id": f"{prefix}-event-{index:06d}",
        "agent": "hotpath-bench",
        "model": "offline",
        "status": "ok",
        "duration_ms": 1.0,
    }


def park_writer(writer: TelemetryWriter) -> None:
    """Stop the writer's background flush thread so it cannot flush.

    A live worker races ``enqueue`` for ``_buffer_lock`` and issues SQLite
    writes mid-measurement, inflating the enqueue cost. Parking leaves the
    buffer untouched; callers shut the writer down afterwards to drain.
    """
    writer._stop_event.set()
    writer._wake_event.set()
    writer._thread.join(timeout=5)


def measure_enqueue_us(
    writer: TelemetryWriter,
    *,
    table: str = DEFAULT_TABLE,
    events: int = DEFAULT_ENQUEUE_EVENTS,
) -> list[float]:
    """µs per ``enqueue`` call with the background worker parked."""
    park_writer(writer)
    samples: list[float] = []
    for i in range(events):
        start = time.perf_counter_ns()
        writer.enqueue(table, record("enq", i))
        samples.append((time.perf_counter_ns() - start) / 1000.0)
    return samples


def measure_sync_us(
    store: TelemetryStore,
    *,
    table: str = DEFAULT_TABLE,
    events: int = DEFAULT_SYNC_EVENTS,
) -> list[float]:
    """µs per ``_insert_one`` event (one transaction per event)."""
    samples: list[float] = []
    for i in range(events):
        start = time.perf_counter_ns()
        store._insert_one(table, record("sync", i))
        samples.append((time.perf_counter_ns() - start) / 1000.0)
    return samples


def measure_batch_us(
    store: TelemetryStore,
    *,
    table: str = DEFAULT_TABLE,
    events: int = DEFAULT_BATCH_BLOCKS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[float]:
    """Amortized µs/event: time a full batch flush, divide by ``batch_size``."""
    samples: list[float] = []
    index = 0
    for _ in range(events):
        rows = [record("bat", index + k) for k in range(batch_size)]
        index += batch_size
        start = time.perf_counter_ns()
        with store.atomic():
            store.insert_many(table, rows)
        samples.append((time.perf_counter_ns() - start) / 1000.0 / batch_size)
    return samples


def run_hotpath(
    *,
    table: str = DEFAULT_TABLE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    enqueue_events: int = DEFAULT_ENQUEUE_EVENTS,
    sync_events: int = DEFAULT_SYNC_EVENTS,
    batch_events: int = DEFAULT_BATCH_BLOCKS,
) -> dict:
    """Measure all three paths on one temp-file DB + WAL and summarize.

    Returns a standalone report (p50/p95/p99 µs/event per path) plus the
    speedup of ``enqueue`` and of amortized ``batch`` over synchronous
    ``_insert_one``, all derived from the measured medians. The writer's
    buffer is sized to hold every enqueued event so no eviction/drop is
    conflated into the enqueue timing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "hotpath.db"
        store = TelemetryStore(db_path, "hotpath-bench")
        store.open()
        writer = TelemetryWriter(
            store,
            batch_size=batch_size,
            buffer_size=max(enqueue_events, 1),
        )
        try:
            enqueue = measure_enqueue_us(writer, table=table, events=enqueue_events)
            sync = measure_sync_us(store, table=table, events=sync_events)
            batch = measure_batch_us(store, table=table, events=batch_events, batch_size=batch_size)
        finally:
            writer.shutdown()
            store.close()

    enq = summarize(enqueue)
    sync = summarize(sync)
    bat = summarize(batch)
    return {
        "units": "us_per_event",
        "table": table,
        "batch_size": batch_size,
        "model": "none",
        "network": False,
        "method": "time.perf_counter_ns, blocked samples; shared tmp DB + WAL",
        "enqueue": enq,
        "sync": sync,
        "batch": bat,
        "speedup_sync_over_enqueue": round(sync["p50"] / enq["p50"], 1),
        "speedup_sync_over_batch": round(sync["p50"] / bat["p50"], 1),
    }
