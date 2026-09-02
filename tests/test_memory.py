"""Tests for MemoryEngine — SQLite, recall, enrich, isolation, resilience."""

from contextlib import suppress

from aios.agents.developer import DeveloperAgent
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.context.packet import ContextPacket
from aios.core import Kernel
from aios.memory import MemoryEngine, ProjectKnowledge, StorageError
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

    assert packet.memory is not None
    assert any(c.rule == "Use type hints" for c in packet.memory.conventions)
    assert any(d.title == "Postgres" for d in packet.memory.decisions)
    assert any(p.name == "Factory" for p in packet.memory.patterns)
    assert any(m.description == "No bare excepts" for m in packet.memory.mistakes)
    engine.shutdown()


def test_env_path_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom" / "memory.db"
    monkeypatch.setenv("AIOS_MEMORY_PATH", str(custom))

    engine = MemoryEngine(project_path=tmp_path)
    engine.initialize()
    assert custom.exists()
    engine.shutdown()


def test_default_path_in_dot_aios(tmp_path):
    (tmp_path / ".aios").mkdir()
    engine = MemoryEngine(project_path=tmp_path, db_path=None)
    assert str(engine._db_path).endswith("/.aios/memory.db")
    engine.initialize()
    assert (tmp_path / ".aios" / "memory.db").exists()
    engine.shutdown()


def test_storage_error_on_open(tmp_path):
    db = tmp_path / "readonly" / "sub" / "memory.db"
    db.parent.mkdir(parents=True)
    db.write_text("not a database")
    store = SQLiteStore(db, "test")
    with suppress(StorageError):
        store.open()
    assert not store.is_open()


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
    with suppress(RuntimeError):
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
        assert not hasattr(agent, "_store")
    finally:
        engine.shutdown()


def test_project_knowledge_to_dict(tmp_path):
    engine = MemoryEngine(project_path=tmp_path, db_path=str(tmp_path / "mem.db"))
    engine.initialize()
    engine.remember_convention("Use type hints")
    engine.remember_decision("Postgres", decision="PostgreSQL")

    knowledge = engine.recall()
    d = knowledge.to_dict()
    assert len(d["conventions"]) == 1
    assert d["conventions"][0]["rule"] == "Use type hints"
    assert len(d["decisions"]) == 1
    assert d["decisions"][0]["decision"] == "PostgreSQL"
    engine.shutdown()


def test_delete_convention_removes_row(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.upsert_convention("Use snake_case", "naming", "manual")
    assert store.delete_convention("Use snake_case") is True
    assert store.get_conventions() == []
    store.close()


def test_delete_decision_removes_row(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.add_decision("SQLite", "persistence", "Use SQLite", "none")
    assert store.delete_decision("SQLite") is True
    assert store.get_decisions() == []
    store.close()


def test_delete_pattern_removes_row(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.add_pattern("Repository", "data access")
    assert store.delete_pattern("Repository") is True
    assert store.get_patterns() == []
    store.close()


def test_delete_mistake_removes_row(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.add_mistake("Never import *", "style", "critical")
    assert store.delete_mistake("Never import *") is True
    assert store.get_mistakes() == []
    store.close()


def test_delete_missing_returns_false(tmp_path):
    """Deleting a row that does not exist reports False on a fresh connection."""
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    assert store.delete_convention("missing") is False
    assert store.delete_decision("missing") is False
    assert store.delete_pattern("missing") is False
    assert store.delete_mistake("missing") is False
    store.close()


def test_delete_when_closed_returns_false(tmp_path):
    """A store that was never opened has no connection, so deletes report False."""
    store = SQLiteStore(tmp_path / "m.db", "p1")
    assert store.delete_convention("x") is False
    assert store.delete_decision("x") is False
    assert store.delete_pattern("x") is False
    assert store.delete_mistake("x") is False


def test_search_matches_across_kinds(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.upsert_convention("prefer fail-fast", "style", "manual")
    store.add_decision("Use fail-fast", "ctx", "Do fail fast", "none")
    store.add_pattern("failfast helper", "helper")
    store.add_mistake("avoid fail-fast here", "style", "warning")
    pairs = {(kind, text) for kind, text in store.search("fail")}
    assert ("convention", "prefer fail-fast") in pairs
    assert ("decision", "Use fail-fast") in pairs
    assert ("pattern", "failfast helper") in pairs
    assert ("mistake", "avoid fail-fast here") in pairs
    store.close()


def test_search_no_match_returns_empty(tmp_path):
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.upsert_convention("Use type hints", "style", "manual")
    assert store.search("zzzznope") == []
    store.close()


def test_get_mistakes_resolved_true(tmp_path):
    """get_mistakes(resolved=True) selects rows with a non-null resolved_at."""
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.add_mistake("open issue", "bug", "warning")
    store.add_mistake("done issue", "bug", "warning")
    store._execute(
        "UPDATE mistakes SET resolved_at=? WHERE description=?",
        (store._now(), "done issue"),
    )
    store._commit()
    assert [m.description for m in store.get_mistakes(resolved=True)] == ["done issue"]
    assert [m.description for m in store.get_mistakes(resolved=False)] == ["open issue"]
    store.close()


def test_writes_are_noop_without_connection(tmp_path):
    """Mutation methods short-circuit silently when the store has no connection."""
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.upsert_convention("rule", "cat", "src")
    store.add_pattern("name", "desc")
    assert store.get_conventions() == []
    assert store.get_patterns() == []
    assert store.get_mistakes() == []
    assert store.get_mistakes(resolved=True) == []


def test_add_pattern_increments_usage_count(tmp_path):
    """Re-adding an existing pattern increments usage_count instead of duplicating."""
    store = SQLiteStore(tmp_path / "m.db", "p1")
    store.open()
    store.add_pattern("Repository", "data access")
    store.add_pattern("Repository", "data access")
    patterns = store.get_patterns()
    assert len(patterns) == 1
    assert patterns[0].usage_count == 2
    store.close()
