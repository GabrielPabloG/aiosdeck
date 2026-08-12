"""Tests for startup profiling hooks (Issue #37, Task A).

Covers the ``kernel.timings`` contract, ``AIOS_PROFILE`` parsing, the
zero-cost NullProfiler, and per-detector timing in the ContextEngine.
"""

from unittest.mock import patch

import pytest

from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.context.packet import DockerInfo
from aios.core import Kernel
from aios.core.profiler import NullProfiler, StartupProfiler, profiling_enabled
from aios.events import EventsEngine


class TestProfileFlagParsing:
    def test_profile_flag_parsing_truthy_values(self, monkeypatch):
        for value in ("true", "1", "yes", "TRUE", "Yes", "YES"):
            monkeypatch.setenv("AIOS_PROFILE", value)
            assert profiling_enabled() is True

    def test_profile_flag_rejects_falsy_values(self, monkeypatch):
        for value in ("false", "0", "no", "on", "garbage", ""):
            monkeypatch.setenv("AIOS_PROFILE", value)
            assert profiling_enabled() is False

    def test_profile_flag_defaults_disabled(self, monkeypatch):
        monkeypatch.delenv("AIOS_PROFILE", raising=False)
        assert profiling_enabled() is False


def _kernel_with_engines(tmp_path, project_path=None):
    kernel = Kernel(project_path=str(project_path or tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.register(EventsEngine())
    return kernel


class TestKernelTimings:
    def test_kernel_timings_empty_when_profiling_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AIOS_PROFILE", raising=False)
        kernel = _kernel_with_engines(tmp_path)
        kernel.start(render_dashboard=False)
        assert kernel.timings == {}
        kernel.shutdown()

    def test_kernel_timings_populated_when_profiling_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIOS_PROFILE", "1")
        kernel = _kernel_with_engines(tmp_path)
        kernel.start(render_dashboard=False)
        timings = kernel.timings
        assert "kernel_start_total_ms" in timings
        assert timings["kernel_start_total_ms"] >= 0
        assert "config_init_ms" in timings["engines"]
        assert "context_init_ms" in timings["engines"]
        assert "events_init_ms" in timings["engines"]
        assert "git_ms" in timings["context_detectors"]
        kernel.shutdown()

    def test_kernel_start_total_and_engine_keys(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIOS_PROFILE", "1")
        kernel = _kernel_with_engines(tmp_path)
        kernel.start(render_dashboard=False)
        timings = kernel.timings
        assert set(timings.keys()) == {"kernel_start_total_ms", "engines", "context_detectors"}
        assert set(timings["engines"].keys()) == {
            "config_init_ms",
            "context_init_ms",
            "events_init_ms",
        }
        assert set(timings["context_detectors"].keys()) == {
            "git_ms",
            "docker_ms",
            "runtime_ms",
            "structure_ms",
        }
        for key, value in timings["engines"].items():
            assert key.endswith("_init_ms")
            assert value >= 0
        for key, value in timings["context_detectors"].items():
            assert key.endswith("_ms")
            assert value >= 0
        kernel.shutdown()


class TestContextEngineTimings:
    def test_context_engine_timings_per_detector(self, tmp_path):
        profiler = StartupProfiler()
        engine = ContextEngine(project_path=tmp_path)
        engine.set_profiler(profiler)
        engine.initialize()
        detectors = profiler.timings["context_detectors"]
        assert set(detectors.keys()) == {"git_ms", "docker_ms", "runtime_ms", "structure_ms"}
        for value in detectors.values():
            assert value >= 0
        engine.shutdown()

    def test_detector_failure_still_records_timing(self, tmp_path, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("docker down")

        monkeypatch.setattr(DockerInfo, "detect", staticmethod(_boom))
        profiler = StartupProfiler()
        engine = ContextEngine(project_path=tmp_path)
        engine.set_profiler(profiler)
        with pytest.raises(RuntimeError, match="docker down"):
            engine.initialize()
        assert "docker_ms" in profiler.timings["context_detectors"]
        assert profiler.timings["context_detectors"]["docker_ms"] >= 0


class TestZeroCost:
    def test_perf_counter_not_called_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AIOS_PROFILE", raising=False)
        kernel = Kernel(project_path=str(tmp_path))
        kernel.register(ConfigEngine(project_path=tmp_path))
        kernel.register(EventsEngine())
        with patch("time.perf_counter") as mock_perf_counter:
            kernel.start(render_dashboard=False)
            kernel.shutdown()
        mock_perf_counter.assert_not_called()

    def test_null_profiler_records_nothing(self):
        profiler = NullProfiler()
        with profiler.measure_engine("config"):
            pass
        with profiler.measure_detector("git"):
            pass
        with profiler.measure_total():
            pass
        assert profiler.timings == {}
