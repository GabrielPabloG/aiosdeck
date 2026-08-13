"""Buffered async batch writer for telemetry events.

TelemetryWriter owns every concern of write-path concurrency:

- Handlers enqueue ``(table, record)`` pairs in O(1) under a deque lock — no
  SQLite work ever touches the EventBus hot path.
- A background daemon thread flushes when the buffer reaches ``batch_size``
  (50 by default) or ``flush_interval`` elapses (500ms by default).
- ``flush()`` drains the buffer, groups records by table, and writes each
  group with ``executemany`` inside a single ``store.atomic()`` transaction
  (one ``BEGIN IMMEDIATE``, one ``COMMIT`` per flush).
- A dedicated ``flush_lock`` serializes flushes. Reads that call ``flush()``
  first — the consistency boundary owned by TelemetryEngine — can never
  observe a buffer drained before its transaction committed.

Failure contract (no automatic synchronous fallback): an error inside the
transaction rolls the whole batch back (the store's atomic block). Locked
errors are retryable — the batch is re-enqueued and retried with backoff
(100/250/500ms by default). Any other error, or a lock that survives every
retry, logs and increments ``events_dropped_total``. The hot path never
falls back to a synchronous write.

Loss window (honest documentation): on graceful shutdown (SIGINT/SIGTERM,
``shutdown()``, or atexit) the buffer is fully drained by the final flush —
nothing buffered is lost. On crash or SIGKILL, events still in the buffer
are lost; the nominal window is the flush interval (~500ms) plus the time to
write the current batch. There is no durability guarantee for unflushed
events.

An ``atexit`` hook registered once per process (idempotent via the active
set) covers library embedding where ``shutdown()`` is never called.
"""

from __future__ import annotations

import atexit
import collections
import logging
import math
import sqlite3
import threading
import time
import weakref

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


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (q / 100.0)
    floor = math.floor(k)
    ceil = math.ceil(k)
    if floor == ceil:
        return float(sorted_vals[int(k)])
    return sorted_vals[floor] * (ceil - k) + sorted_vals[ceil] * (k - floor)


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
        """Buffer one record. O(1); when the buffer is full the oldest entry
        is evicted and counted in ``events_dropped_total``."""
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
        """Stop the worker thread and drain the remaining buffer.

        Idempotent: repeated calls are no-ops. The thread is joined (up to
        5s) and a final synchronous flush writes whatever is left, so a
        graceful shutdown loses nothing.
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
                "flush_duration_p50_ms": _percentile(durations, 50),
                "flush_duration_p95_ms": _percentile(durations, 95),
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
