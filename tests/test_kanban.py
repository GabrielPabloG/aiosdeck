"""Tests for KanbanEngine — scrum board persistence, TDD gates, flow validation."""

import pytest

from aios.scheduler import KanbanBoard, KanbanCard, KanbanEngine, KanbanError, KanbanSubtask

COLUMNS = ("Backlog", "Todo", "InProgress", "Review", "Done")


def _make_engine(tmp_path, name: str = "kanban.db") -> KanbanEngine:
    engine = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / name))
    engine.initialize()
    return engine


def test_kanban_engine_implements_engine_protocol(tmp_path):
    engine = KanbanEngine(project_path=tmp_path)
    assert engine.name == "scheduler"
    engine.initialize()
    assert engine.health_check() is True
    engine.shutdown()


def test_kanban_board_create(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    assert isinstance(board, KanbanBoard)
    assert board.id is not None
    assert board.name == "Sprint 1"
    assert board.status == "active"
    engine.shutdown()


def test_kanban_board_retrieval(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 2")
    loaded = engine.get_board(board.id)
    assert loaded is not None
    assert loaded.name == "Sprint 2"
    assert loaded.project_id == engine._project_id
    engine.shutdown()


def test_kanban_card_create_in_backlog(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Add OAuth", description="OAuth2 login")
    assert isinstance(card, KanbanCard)
    assert card.id is not None
    assert card.column == "Backlog"
    assert card.tdd_gate is False
    engine.shutdown()


def test_kanban_card_move_through_flow(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Add OAuth")

    for column in ("Todo", "InProgress", "Review"):
        engine.move_card(card.id, column)

    moved = engine.get_card(card.id)
    assert moved.column == "Review"
    engine.shutdown()


def test_kanban_invalid_skip_raises(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Jump ahead")

    with pytest.raises(KanbanError):
        engine.move_card(card.id, "InProgress")
    engine.shutdown()


def test_kanban_tdd_gate_blocks_done(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Feature without tests")
    engine.move_card(card.id, "Todo")

    with pytest.raises(KanbanError) as excinfo:
        engine.move_card(card.id, "Done")
    assert "test" in str(excinfo.value).lower()

    blocked = engine.get_card(card.id)
    assert blocked.column == "Todo"
    assert blocked.tdd_gate is False
    engine.shutdown()


def test_kanban_tdd_gate_allows_done(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Tested feature")
    engine.move_card(card.id, "Todo")
    engine.move_card(card.id, "InProgress")
    engine.move_card(card.id, "Review")

    engine.pass_tdd_gate(card.id)
    engine.move_card(card.id, "Done")

    done = engine.get_card(card.id)
    assert done.column == "Done"
    assert done.tdd_gate is True
    engine.shutdown()


def test_kanban_card_persistence_across_sessions(tmp_path):
    db = tmp_path / "kanban.db"
    engine_a = KanbanEngine(project_path=tmp_path, db_path=str(db))
    engine_a.initialize()
    board = engine_a.create_board("Sprint 3")
    card = engine_a.create_card(board_id=board.id, title="Persist me")
    card_id = card.id
    engine_a.shutdown()

    engine_b = KanbanEngine(project_path=tmp_path, db_path=str(db))
    engine_b.initialize()
    loaded = engine_b.get_card(card_id)
    assert loaded is not None
    assert loaded.title == "Persist me"
    assert loaded.column == "Backlog"
    engine_b.shutdown()


def test_kanban_subtask_lifecycle(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Parent card")
    engine.move_card(card.id, "Todo")

    subtask = engine.create_subtask(card_id=card.id, description="Write failing test")
    assert isinstance(subtask, KanbanSubtask)
    assert subtask.done is False

    engine.complete_subtask(subtask.id)

    card_with_subtasks = engine.get_card(card.id)
    assert len(card_with_subtasks.subtasks) == 1
    assert card_with_subtasks.subtasks[0].done is True
    assert card_with_subtasks.subtasks[0].description == "Write failing test"
    engine.shutdown()


def test_kanban_boards_are_project_isolated(tmp_path):
    proj_a = tmp_path / "project-a"
    proj_b = tmp_path / "project-b"
    proj_a.mkdir()
    proj_b.mkdir()
    db = tmp_path / "kanban.db"

    engine_a = KanbanEngine(project_path=proj_a, db_path=str(db))
    engine_a.initialize()
    engine_a.create_board("Sprint A")
    engine_a.shutdown()

    engine_b = KanbanEngine(project_path=proj_b, db_path=str(db))
    engine_b.initialize()
    engine_b.create_board("Sprint B")
    engine_b.shutdown()

    engine_a2 = KanbanEngine(project_path=proj_a, db_path=str(db))
    engine_a2.initialize()
    boards = engine_a2.list_boards()
    assert [b.name for b in boards] == ["Sprint A"]
    engine_a2.shutdown()


def test_kanban_card_columns_are_validated(tmp_path):
    engine = _make_engine(tmp_path)
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Bad column")

    with pytest.raises(KanbanError):
        engine.move_card(card.id, "Sideways")
    engine.shutdown()
