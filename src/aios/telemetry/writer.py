"""Buffered async batch writer for telemetry events.

Owns every concern of write-path concurrency:

- Handlers enqueue ``(table, record)`` in O(1) — no SQLite work ever
  touches the EventBus hot path.
- A daemon thread flushes at ``batch_size`` (50) or ``flush_interval``
  (500ms), grouping records by table into one ``executemany`` per table
  inside a single ``store.atomic()`` transaction.
- A dedicated ``flush_lock`` serializes flushes: reads that call
  ``flush()`` first (TelemetryEngine's consistency boundary) can never see
  a drained buffer whose transaction has not committed.

Failure contract (no automatic synchronous fallback): a transaction error
rolls the batch back. Locked errors re-enqueue the batch and retry with
backoff (100/250/500ms); anything else, or a persistent lock, logs and
increments ``events_dropped_total``.

Loss window (honest): graceful shutdown (SIGINT/SIGTERM, ``shutdown()``,
atexit) fully drains the buffer — zero loss. On crash or SIGKILL, unflushed
events are lost; the nominal window is the flush interval (~500ms) plus the
current batch write. No durability guarantee for unflushed events.

The atexit hook is registered once per process and is idempotent (active
set), covering library embedding where ``shutdown()`` is never called.
"""

from __future__ import annotations

import atexit
import collections
import logging
import sqlite3
import threading
import time
import weakref

from aios.telemetry.benchmark import percentile
from aios.telemetry.store import TelemetryError

logger = logging.getLogger("aios.telemetry.writer")

DEFAULT_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL = 0.5
DEFAULT_BUFFER_SIZE = 10_000
DEFAULT_BACKOFF = (0.1, 0.25, 0.5)

_ACTIVE: weakref.WeakSet = weakref.WeakSet()


def _is_locked(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


class TelemetryWriter:
    """Buffered batched writer with a single background flush thread."""

    def __init__(
        self,
        store,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
    ) -> None:
        self._store = store
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._backoff = backoff
        self._buffer: collections.deque = collections.deque(maxlen=buffer_size)
        self._buffer_lock = threading.RLock()
        self._flush_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._flush_count = 0
        self._flushed_total = 0
        self._dropped_total = 0
        self._durations: collections.deque = collections.deque(maxlen=100)
        self._shutdown = False
        self._thread = threading.Thread(target=self._run, name="telemetry-writer", daemon=True)
        self._thread.start()
        _ACTIVE.add(self)

    # ------------------------------------------------------------------
    # Hot path
    # ------------------------------------------------------------------

    def enqueue(self, table: str, record: dict) -> None:
        """Buffer one record in O(1); a full buffer evicts the oldest entry
        and counts it in ``events_dropped_total``."""
        with self._buffer_lock:
            if len(self._buffer) == self._buffer.maxlen:
                self._dropped_total += 1
            self._buffer.append((table, record))
            if len(self._buffer) >= self._batch_size:
                self._wake_event.set()

    # ------------------------------------------------------------------
    # Flush (shared by timer, shutdown, and the read consistency boundary)
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Drain the buffer and write it in one transaction.

        Serialized by ``flush_lock``: callers that flush before reading can
        never observe a drained buffer whose transaction has not committed.
        Locked errors re-enqueue the batch and retry with backoff; anything
        else, or a persistent lock, drops the batch and increments
        ``events_dropped_total``.
        """
        with self._flush_lock:
            batch = self._drain()
            if not batch:
                return
            retries = len(self._backoff)
            attempt = 0
            while True:
                try:
                    self._write(batch)
                    return
                except sqlite3.Error as exc:
                    if _is_locked(exc) and attempt < retries:
                        self._requeue(batch)
                        logger.warning(
                            "telemetry flush locked (%s); retry %d/%d",
                            exc,
                            attempt + 1,
                            retries,
                        )
                        time.sleep(self._backoff[attempt])
                        attempt += 1
                        batch = self._drain()
                        if not batch:
                            return
                        continue
                    self._drop(batch, exc)
                    return
                except TelemetryError as exc:
                    self._drop(batch, exc)
                    return

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop the worker (join up to 5s) and drain the remaining buffer.

        Idempotent: repeated calls are no-ops, so graceful shutdown loses
        nothing buffered.
        """
        if self._shutdown:
            return
        self._shutdown = True
        self._stop_event.set()
        self._wake_event.set()
        self._thread.join(timeout=5)
        self.flush()
        _ACTIVE.discard(self)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict:
        """Gauges and counters for observability of the writer itself."""
        with self._buffer_lock:
            durations = sorted(self._durations)
            return {
                "buffer_size": len(self._buffer),
                "flush_count": self._flush_count,
                "events_flushed_total": self._flushed_total,
                "events_dropped_total": self._dropped_total,
                "flush_duration_p50_ms": percentile(durations, 50),
                "flush_duration_p95_ms": percentile(durations, 95),
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.wait(self._flush_interval)
            self._wake_event.clear()
            if not self._stop_event.is_set():
                self.flush()

    def _drain(self) -> list[tuple[str, dict]]:
        with self._buffer_lock:
            batch = list(self._buffer)
            self._buffer.clear()
            return batch

    def _requeue(self, batch: list[tuple[str, dict]]) -> None:
        with self._buffer_lock:
            overflow = len(batch) - (self._buffer.maxlen - len(self._buffer))
            if overflow > 0:
                self._dropped_total += overflow
            self._buffer.extendleft(reversed(batch))

    def _write(self, batch: list[tuple[str, dict]]) -> None:
        grouped: dict[str, list[dict]] = {}
        for table, record in batch:
            grouped.setdefault(table, []).append(record)
        started = time.monotonic()
        with self._store.atomic():
            for table, rows in grouped.items():
                self._store.insert_many(table, rows)
        duration_ms = (time.monotonic() - started) * 1000.0
        with self._buffer_lock:
            self._flush_count += 1
            self._flushed_total += len(batch)
            self._durations.append(duration_ms)

    def _drop(self, batch: list[tuple[str, dict]], exc: Exception) -> None:
        with self._buffer_lock:
            self._dropped_total += len(batch)
        logger.error("telemetry flush failed, dropped %d events: %s", len(batch), exc)


def _shutdown_all() -> None:
    for writer in list(_ACTIVE):
        writer.shutdown()


atexit.register(_shutdown_all)
