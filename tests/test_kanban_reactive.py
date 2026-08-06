"""Tests for the reactive Kanban live board — event emission and live rendering.

Covers v0.9: KanbanEngine publishing to the Event Bus on card/subtask
mutations, and the live render callback that redraws the board in --run.
"""

import io
import sys
from unittest.mock import MagicMock

import pytest

from aios.agents.models import AgentResult
from aios.cli.commands import _execute_subtasks
from aios.events import EventsEngine
from aios.events.bus import EventBus
from aios.events.events import (
    KANBAN_CARD_MOVED,
    KANBAN_SUBTASK_COMPLETED,
    KANBAN_SUBTASK_CREATED,
)
from aios.scheduler import COLUMNS, KanbanEngine


def _make_engine(tmp_path, event_bus=None, name: str = "kanban.db") -> KanbanEngine:
    engine = KanbanEngine(
        project_path=tmp_path,
        db_path=str(tmp_path / name),
        event_bus=event_bus,
    )
    engine.initialize()
    return engine


def _make_board_card(engine: KanbanEngine) -> tuple:
    board = engine.create_board("Sprint 1")
    card = engine.create_card(board_id=board.id, title="Add OAuth")
    return board, card


def _card_moved_calls(bus: MagicMock) -> list:
    return [c for c in bus.publish.call_args_list if c.args[0] == KANBAN_CARD_MOVED]


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


def test_move_card_emits_event(tmp_path):
    bus = MagicMock()
    engine = _make_engine(tmp_path, event_bus=bus)
    board, card = _make_board_card(engine)

    engine.move_card(card.id, "Todo")

    calls = _card_moved_calls(bus)
    assert len(calls) == 1
    topic, payload = calls[0].args
    assert topic == KANBAN_CARD_MOVED
    assert payload["card_id"] == card.id
    assert payload["card_title"] == "Add OAuth"
    assert payload["from_column"] == "Backlog"
    assert payload["to_column"] == "Todo"
    assert payload["board_id"] == board.id
    engine.shutdown()


def test_move_card_same_column_does_not_emit(tmp_path):
    bus = MagicMock()
    engine = _make_engine(tmp_path, event_bus=bus)
    _, card = _make_board_card(engine)
    engine.move_card(card.id, "Todo")

    bus.publish.reset_mock()
    engine.move_card(card.id, "Todo")

    assert _card_moved_calls(bus) == []
    engine.shutdown()


def test_move_card_no_bus_does_not_crash(tmp_path):
    engine = _make_engine(tmp_path)
    _, card = _make_board_card(engine)

    moved = engine.move_card(card.id, "Todo")

    assert moved.column == "Todo"
    engine.shutdown()


def test_create_subtask_emits_event(tmp_path):
    bus = MagicMock()
    engine = _make_engine(tmp_path, event_bus=bus)
    _, card = _make_board_card(engine)

    subtask = engine.create_subtask(card_id=card.id, description="failing test (RED)")

    calls = [c for c in bus.publish.call_args_list if c.args[0] == KANBAN_SUBTASK_CREATED]
    assert len(calls) == 1
    topic, payload = calls[0].args
    assert topic == KANBAN_SUBTASK_CREATED
    assert payload["subtask_id"] == subtask.id
    assert payload["card_id"] == card.id
    assert payload["description"] == "failing test (RED)"
    engine.shutdown()


def test_complete_subtask_emits_event(tmp_path):
    bus = MagicMock()
    engine = _make_engine(tmp_path, event_bus=bus)
    _, card = _make_board_card(engine)
    subtask = engine.create_subtask(card_id=card.id, description="failing test (RED)")

    bus.publish.reset_mock()
    engine.complete_subtask(subtask.id)

    calls = [c for c in bus.publish.call_args_list if c.args[0] == KANBAN_SUBTASK_COMPLETED]
    assert len(calls) == 1
    topic, payload = calls[0].args
    assert topic == KANBAN_SUBTASK_COMPLETED
    assert payload["subtask_id"] == subtask.id
    engine.shutdown()


def test_set_event_bus_sets_internal_bus(tmp_path):
    engine = _make_engine(tmp_path)
    bus = EventBus()

    engine.set_event_bus(bus)

    assert engine._bus is bus
    engine.shutdown()


# ---------------------------------------------------------------------------
# Live render callback
# ---------------------------------------------------------------------------


def test_live_render_callback_invoked(tmp_path):
    bus = EventBus()
    engine = _make_engine(tmp_path, event_bus=bus)
    _, card = _make_board_card(engine)

    received = []
    bus.subscribe(KANBAN_CARD_MOVED, received.append)

    engine.move_card(card.id, "Todo")

    assert len(received) == 1
    assert received[0].topic == KANBAN_CARD_MOVED
    assert received[0].payload["to_column"] == "Todo"
    engine.shutdown()


def test_live_render_callback_redraws_board_summary(tmp_path):
    bus = EventBus()
    engine = _make_engine(tmp_path, event_bus=bus)
    board, card = _make_board_card(engine)

    rendered = []

    def on_card_moved(_event):
        summary = {column: 0 for column in COLUMNS}
        for c in engine.list_cards(board.id):
            summary[c.column] += 1
        rendered.append(summary)

    bus.subscribe(KANBAN_CARD_MOVED, on_card_moved)

    engine.move_card(card.id, "Todo")
    engine.move_card(card.id, "InProgress")

    expected = [
        {"Backlog": 0, "Todo": 1, "InProgress": 0, "Review": 0, "Done": 0},
        {"Backlog": 0, "Todo": 0, "InProgress": 1, "Review": 0, "Done": 0},
    ]
    assert rendered == expected
    engine.shutdown()


# ---------------------------------------------------------------------------
# CLI --run live redraw
# ---------------------------------------------------------------------------


def _make_live_kernel(tmp_path) -> tuple:
    events = EventsEngine()
    events.initialize()

    scheduler = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()

    developer = MagicMock()
    developer.execute.return_value = AgentResult(success=True, output="ok", errors=[])

    kernel = MagicMock()
    engine_map = {
        "scheduler": scheduler,
        "developer": developer,
        "events": events,
    }
    kernel.get_engine.side_effect = engine_map.get
    return kernel, scheduler


def test_cli_run_redraws_live_board(tmp_path):
    kernel, scheduler = _make_live_kernel(tmp_path)
    plan = {"subtasks": [{"id": "1", "description": "Add login"}]}

    stderr = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stderr", stderr)
        _execute_subtasks(plan, "add login", kernel, MagicMock())

    output = stderr.getvalue()
    assert "\r\033[K" in output
    assert "InProgress (1)" in output
    assert "Done (1)" in output
    scheduler.shutdown()
