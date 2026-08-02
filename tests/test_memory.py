"""Tests for MemoryEngine — SQLite, recall, enrich, isolation, resilience."""

import sqlite3
from contextlib import suppress

from aios.agents.developer import DeveloperAgent
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.context.packet import ContextPacket
from aios.core import Kernel
from aios.memory import MemoryEngine, ProjectKnowledge
from aios.memory.store import SQLiteStore


def test_schema_created(tmp_path):
    db = tmp_path / "test.db"
    store = SQLiteStore(db, "project-1")
    store.open()
    tables = [
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    assert "conventions" in tables
    assert "decisions" in tables
    assert "patterns" in tables
    assert "mistakes" in tables
    store.close()


def test_recall_empty(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    knowledge = engine.recall()
    assert isinstance(knowledge, ProjectKnowledge)
    assert knowledge.is_empty is True
    engine.shutdown()


def test_remember_convention(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_convention("Use snake_case", category="naming", source="manual")
    knowledge = engine.recall()
    assert len(knowledge.conventions) == 1
    assert knowledge.conventions[0].rule == "Use snake_case"
    engine.shutdown()


def test_remember_decision(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_decision("SQLite", context="Need persistence", decision="Use SQLite")
    knowledge = engine.recall()
    assert len(knowledge.decisions) == 1
    assert knowledge.decisions[0].title == "SQLite"
    engine.shutdown()


def test_remember_pattern(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_pattern("Repository", description="Data access pattern")
    knowledge = engine.recall()
    assert len(knowledge.patterns) == 1
    assert knowledge.patterns[0].name == "Repository"
    engine.shutdown()


def test_remember_mistake(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_mistake("Never import *", category="style", severity="critical")
    knowledge = engine.recall()
    assert len(knowledge.mistakes) == 1
    assert knowledge.mistakes[0].severity == "critical"
    engine.shutdown()


def test_convention_dedup(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_convention("Use snake_case", category="naming")
    engine.remember_convention("Use snake_case", category="style", source="README")
    knowledge = engine.recall()
    assert len(knowledge.conventions) == 1
    assert knowledge.conventions[0].category == "style"
    engine.shutdown()


def test_project_isolation(tmp_path):
    db = tmp_path / "mem.db"
    proj_a = tmp_path / "project-a"
    proj_b = tmp_path / "project-b"
    proj_a.mkdir()
    proj_b.mkdir()

    engine_a = MemoryEngine(project_path=proj_a, db_path=str(db))
    engine_a.initialize()
    engine_a.remember_convention("Rule A")
    engine_a.shutdown()

    engine_b = MemoryEngine(project_path=proj_b, db_path=str(db))
    engine_b.initialize()
    engine_b.remember_convention("Rule B")
    engine_b.shutdown()

    engine_a2 = MemoryEngine(project_path=proj_a, db_path=str(db))
    engine_a2.initialize()
    knowledge = engine_a2.recall()
    assert len(knowledge.conventions) == 1
    assert knowledge.conventions[0].rule == "Rule A"
    engine_a2.shutdown()


def test_enrich_context(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_convention("Use type hints", category="style")
    engine.remember_decision("Postgres", context="Scalability", decision="PostgreSQL")
    engine.remember_pattern("Factory")
    engine.remember_mistake("No bare excepts")

    packet = ContextPacket()
    engine.enrich_context(packet)

    assert "Use type hints" in packet.memory["conventions"]
    assert "Postgres" in packet.memory["decisions"]
    assert "Factory" in packet.memory["patterns"]
    assert "No bare excepts" in packet.memory["mistakes"]
    engine.shutdown()


def test_env_path_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom" / "memory.db"
    monkeypatch.setenv("AIOS_MEMORY_PATH", str(custom))

    engine = MemoryEngine(project_path=tmp_path)
    engine.initialize()
    assert custom.exists()
    engine.shutdown()


def test_memory_optional(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.start()
    status = kernel.status()
    assert status["engines"]["config"] == "ready"
    assert status["engines"]["context"] == "ready"


def test_corrupt_db(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_text("this is not sqlite")

    engine = MemoryEngine(project_path=tmp_path, db_path=str(db))
    with suppress(sqlite3.DatabaseError):
        engine.initialize()

    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(engine)
    kernel.start()
    status = kernel.status()
    assert status["engines"]["memory"] in ("error", "ready", "degraded")
    assert len(status["errors"]) <= 1


def test_agent_no_direct_memory(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()

    try:
        agent = DeveloperAgent(None)
        assert not hasattr(agent, "_memory")
    finally:
        engine.shutdown()
