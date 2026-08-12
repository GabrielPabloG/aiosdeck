"""Startup profiler — optional timing collection, zero-cost when disabled.

``AIOS_PROFILE`` (truthy: ``true``/``1``/``yes``) turns on per-engine and
per-detector timing collection. The Kernel reads it once in its constructor
and hands the resulting profiler to the ContextEngine; nothing is re-read
inside individual detectors. When disabled a NullProfiler stands in: no
timings are recorded and ``time.perf_counter`` is never called.
"""

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

PROFILE_TRUTHY = ("true", "1", "yes")


def profiling_enabled() -> bool:
    """True when ``AIOS_PROFILE`` is set to a truthy value."""
    return os.environ.get("AIOS_PROFILE", "").strip().lower() in PROFILE_TRUTHY


class Profiler(Protocol):
    """Minimal timing surface shared by the real and null profilers."""

    @property
    def timings(self) -> dict: ...

    def measure_engine(self, name: str) -> Iterator[None]: ...

    def measure_detector(self, name: str) -> Iterator[None]: ...

    def measure_total(self) -> Iterator[None]: ...


class NullProfiler:
    """Zero-cost stand-in — never calls ``time.perf_counter``."""

    @property
    def timings(self) -> dict:
        return {}

    @contextmanager
    def measure_engine(self, name: str) -> Iterator[None]:
        yield

    @contextmanager
    def measure_detector(self, name: str) -> Iterator[None]:
        yield

    @contextmanager
    def measure_total(self) -> Iterator[None]:
        yield


class StartupProfiler:
    """Collects startup timings while ``AIOS_PROFILE`` is enabled."""

    def __init__(self) -> None:
        self._engines: dict[str, float] = {}
        self._detectors: dict[str, float] = {}
        self._total_ms: float | None = None

    @property
    def timings(self) -> dict:
        return {
            "kernel_start_total_ms": self._total_ms,
            "engines": dict(self._engines),
            "context_detectors": dict(self._detectors),
        }

    @contextmanager
    def measure_engine(self, name: str) -> Iterator[None]:
        with self._measure(self._engines, f"{name}_init_ms"):
            yield

    @contextmanager
    def measure_detector(self, name: str) -> Iterator[None]:
        with self._measure(self._detectors, f"{name}_ms"):
            yield

    @contextmanager
    def measure_total(self) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self._total_ms = _elapsed_ms(start)

    @contextmanager
    def _measure(self, target: dict[str, float], key: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            target[key] = _elapsed_ms(start)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def create_profiler() -> Profiler:
    """Build the active profiler for this process from ``AIOS_PROFILE``."""
    if profiling_enabled():
        return StartupProfiler()
    return NullProfiler()
