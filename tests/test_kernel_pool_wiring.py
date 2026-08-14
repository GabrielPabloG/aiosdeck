"""Kernel/factory/engine pool wiring (Issue #38)."""

from unittest.mock import MagicMock

import aios.storage.pool as pool_module
from aios.core import Kernel
from aios.core.factory import create_kernel
from aios.knowledge.engine import KnowledgeEngine
from aios.learning.engine import LearningEngine
from aios.memory.engine import MemoryEngine
from aios.scheduler.engine import KanbanEngine
from aios.storage.pool import ConnectionPool
from aios.telemetry.engine import TelemetryEngine

_STORE_ENGINES = ("memory", "learning", "scheduler", "telemetry", "knowledge")


class _SpyPool(ConnectionPool):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    def close_all(self) -> None:
        self._events.append("pool.close_all")
        super().close_all()


class _RecordingEngine:
    def __init__(self, engine, events: list[str]) -> None:
        self._engine = engine
        self._events = events
        self.name = engine.name

    def initialize(self) -> None:
        self._engine.initialize()

    def health_check(self) -> bool:
        return self._engine.health_check()

    def shutdown(self) -> None:
        self._events.append(f"shutdown:{self.name}")
        store = getattr(self._engine, "_store", None)
        if store is not None and self.name == "telemetry":
            store.insert_execution({"event_id": "final-write", "execution_id": "final-write"})
        self._engine.shutdown()


def test_create_kernel_injects_pool(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    connects = []
    real_connect = pool_module.connect_threadsafe

    def counting_connect(db_path):
        connects.append(str(db_path))
        return real_connect(db_path)

    monkeypatch.setattr(pool_module, "connect_threadsafe", counting_connect)

    kernel = create_kernel(tmp_path)
    kernel.start(render_dashboard=False, quiet=True)

    assert len(connects) == 1
    stores = [kernel.get_engine(name)._store for name in _STORE_ENGINES]
    assert all(store is not None for store in stores)
    assert len({id(store._conn) for store in stores}) == 1
    kernel.shutdown()


def test_shared_connection_survives_engine_close(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    kernel = create_kernel(tmp_path)
    kernel.start(render_dashboard=False, quiet=True)

    kernel.get_engine("memory").shutdown()

    scheduler = kernel.get_engine("scheduler")
    assert scheduler.create_board("after-memory-close").name == "after-memory-close"

    telemetry = kernel.get_engine("telemetry")
    telemetry.record_retrieval({"agent": "t", "query": "q"})
    assert len(telemetry.query_retrieval(agent="t")) == 1

    kernel.shutdown()


def test_kernel_shutdown_closes_pool_after_engines(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    events: list[str] = []
    pool = _SpyPool(events)
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(
        _RecordingEngine(MemoryEngine(project_path=tmp_path, connection_pool=pool), events)
    )
    kernel.register(
        _RecordingEngine(LearningEngine(project_path=tmp_path, connection_pool=pool), events)
    )
    kernel.register(
        _RecordingEngine(KanbanEngine(project_path=tmp_path, connection_pool=pool), events)
    )
    kernel.register(
        _RecordingEngine(TelemetryEngine(project_path=tmp_path, connection_pool=pool), events)
    )
    kernel.register(
        _RecordingEngine(KnowledgeEngine(project_path=tmp_path, connection_pool=pool), events)
    )
    kernel.set_storage_pool(pool)

    kernel.start(render_dashboard=False, quiet=True)
    kernel.shutdown()

    assert set(events[:-1]) == {f"shutdown:{name}" for name in _STORE_ENGINES}
    assert events[-1] == "pool.close_all"
    assert pool._connections == {}


def test_kernel_shutdown_stops_executor_before_storage_pool(tmp_path):
    events: list[str] = []
    executor = MagicMock()
    executor.shutdown.side_effect = lambda: events.append("executor.shutdown")
    pool = _SpyPool(events)
    kernel = Kernel(project_path=str(tmp_path))
    kernel.set_executor(executor)
    kernel.set_storage_pool(pool)

    kernel.shutdown()

    assert events == ["executor.shutdown", "pool.close_all"]


def test_kernel_shutdown_without_pool_noop(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.start(render_dashboard=False, quiet=True)
    kernel.shutdown()
