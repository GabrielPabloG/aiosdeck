"""Tests for the telemetry lock-contention micro-benchmark (Issue #70).

Measure the cost of concurrent ``insert_execution`` (the synchronous pre-batch
path, one BEGIN/COMMIT per event) across three scenarios — shared single
connection/db, independent per-thread connection/own-file, and a shared db
written by a background ``TelemetryWriter`` — as an off-line, deterministic
micro-benchmark. The closed ``GROUPS``/``METRICS`` schema is intentionally NOT
used: this is a standalone instrument, so no schema bump, no model, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aios.telemetry.contention import run_contention
from aios.telemetry.schema import SCHEMA_VERSION


def _lat(report: dict, scenario: str) -> dict:
    return report["scenarios"][scenario]["latency_us"]


@pytest.mark.parametrize("threads", [1, 2])
def test_contention_shared_serializes_but_correct(threads, tmp_path: Path):
    report = run_contention(tmp_path, threads=threads, ops_per_thread=20, warmup=3)
    scenario = report["scenarios"]["shared_n_threads"]
    assert scenario["persisted"] == threads * (3 + 20)
    assert all(v > 0 for v in scenario["latency_us"].values())


def test_contention_shared_and_independent_persist_all(tmp_path: Path):
    report = run_contention(tmp_path, threads=4, ops_per_thread=30, warmup=4)
    shared = report["scenarios"]["shared_n_threads"]
    independent = report["scenarios"]["independent_n_threads"]
    expected = 4 * (4 + 30)
    assert shared["persisted"] == expected
    assert independent["persisted"] == expected
    for q in ("p50", "p95", "p99"):
        assert shared["latency_us"][q] > 0
        assert independent["latency_us"][q] > 0


def test_contention_degradation_is_measured_not_asserted(tmp_path: Path):
    report = run_contention(tmp_path, threads=4, ops_per_thread=30, warmup=4)
    shared = _lat(report, "shared_n_threads")
    independent = _lat(report, "independent_n_threads")
    degradation = report["degradation"]["shared_vs_independent"]
    for q in ("p50", "p95", "p99"):
        assert degradation[q] == pytest.approx(shared[q] / independent[q], rel=1e-6)


def test_contention_flush_shares_connection_atomic(tmp_path: Path):
    report = run_contention(tmp_path, threads=4, ops_per_thread=60, warmup=3)
    scenario = report["scenarios"]["flush_concurrent"]
    assert scenario["flushes_observed"] >= 1
    assert scenario["events_dropped"] == 0
    assert scenario["events_flushed_total"] == 4 * (3 + 60)
    assert scenario["persisted"] == 4 * (3 + 60)


def test_contention_deterministic_no_model_network(tmp_path: Path):
    module_src = (
        Path(__file__).resolve().parents[1] / "src/aios/telemetry/contention.py"
    ).read_text()
    for token in ("aios.runtime", "aios.routing", "urllib", "socket", "requests", "httpx"):
        assert token not in module_src, f"contention must stay off-line, found {token!r}"
    report = run_contention(tmp_path, threads=2, ops_per_thread=10, warmup=2)
    assert report["model"] is None
    assert report["network"] is False


def test_contention_schema_untouched(tmp_path: Path):
    assert SCHEMA_VERSION == "1.1"
    report = run_contention(tmp_path, threads=2, ops_per_thread=10, warmup=2)
    assert "schema_version" not in report
    assert "results" not in report


def test_contention_metadata_present(tmp_path: Path):
    report = run_contention(tmp_path, threads=2, ops_per_thread=10, warmup=2)
    metadata = report["metadata"]
    assert metadata["sqlite_version"]
    assert metadata["system_info"]["cpu_count"] > 0
    assert metadata["threads"] == 2
    assert metadata["ops_per_thread"] == 10
