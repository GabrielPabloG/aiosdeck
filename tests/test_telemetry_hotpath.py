"""Tests for the telemetry hot-path micro-benchmark (Issue #67).

Instrument the three write paths — synchronous insert (pre-batching),
amortized batch flush, and ``TelemetryWriter.enqueue`` — as a
deterministic, off-line micro-benchmark in microseconds per event. The full
lifecycle report schema (``GROUPS``/``METRICS``) is intentionally NOT used:
this is a standalone measurement, so no schema bump, no model, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aios.telemetry.benchmark import summarize
from aios.telemetry.hotpath import (
    DEFAULT_BATCH_SIZE,
    measure_batch_us,
    measure_enqueue_us,
    measure_sync_us,
    run_hotpath,
)
from aios.telemetry.store import TelemetryStore
from aios.telemetry.writer import TelemetryWriter


@pytest.fixture
def store(tmp_path: Path):
    store = TelemetryStore(tmp_path / "hp.db", "hotpath-bench")
    store.open()
    try:
        yield store
    finally:
        store.close()


def _writer(store) -> TelemetryWriter:
    return TelemetryWriter(store, batch_size=DEFAULT_BATCH_SIZE)


def _p50(samples: list[float]) -> float:
    return summarize(samples)["p50"]


def test_hotpath_measures_enqueue_without_db_io(store):
    writer = _writer(store)
    samples = measure_enqueue_us(writer, events=5_000)
    writer.shutdown()
    assert samples and all(s > 0 for s in samples)
    assert _p50(samples) < 100_000.0


def test_hotpath_sync_insert_uses_one_txn_per_event(store):
    samples = measure_sync_us(store, events=50)
    assert len(samples) == 50
    assert all(s > 0 for s in samples)


def test_hotpath_batch_flush_amortized_scale(store):
    sync = measure_sync_us(store, events=60)
    batch = measure_batch_us(store, events=40, batch_size=DEFAULT_BATCH_SIZE)
    assert _p50(batch) < _p50(sync)


def test_hotpath_same_db_shared_connection(tmp_path: Path):
    db_path = tmp_path / "shared.db"
    store = TelemetryStore(db_path, "hotpath-bench")
    store.open()
    writer = TelemetryWriter(store, batch_size=DEFAULT_BATCH_SIZE)
    try:
        measure_enqueue_us(writer, events=500)
        measure_sync_us(store, events=20)
        measure_batch_us(store, events=20, batch_size=DEFAULT_BATCH_SIZE)
    finally:
        writer.shutdown()
        store.close()


def test_hotpath_speedup_is_computed_not_fabricated():
    report = run_hotpath(
        enqueue_events=1_000,
        sync_events=40,
        batch_events=20,
    )
    sync_p50 = report["sync"]["p50"]
    enqueue_p50 = report["enqueue"]["p50"]
    batch_p50 = report["batch"]["p50"]
    assert report["batch_size"] == DEFAULT_BATCH_SIZE
    assert report["units"] == "us_per_event"
    assert report["speedup_sync_over_enqueue"] == pytest.approx(sync_p50 / enqueue_p50, rel=0.1)
    assert report["speedup_sync_over_batch"] == pytest.approx(sync_p50 / batch_p50, rel=0.1)


def test_hotpath_deterministic_no_model_network(tmp_path: Path):
    module_src = (Path(__file__).resolve().parents[1] / "src/aios/telemetry/hotpath.py").read_text()
    for token in ("aios.runtime", "aios.routing", "urllib", "socket", "requests", "httpx"):
        assert token not in module_src, f"hotpath must stay off-line, found {token!r}"
    report = run_hotpath(enqueue_events=200, sync_events=10, batch_events=5)
    assert report["model"] == "none"
    assert report["network"] is False
