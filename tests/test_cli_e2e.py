"""End-to-end tests for `aios plan <intent> --run`.

The full stack runs against a real Kernel: real Context, Memory, Scheduler
(SQLite at .aios/memory.db) and Events engines. Only the LLM-backed agents
(planner, developer) are stubbed, since a model is not available in CI.

These tests validate the product contract of v0.9.1:
- the planned subtask list is printed before execution,
- all cards are populated in the Backlog before the loop starts,
- `.aios/memory.db` reflects the final kanban state (Done / blocked),
- kanban events were emitted on the Event Bus.
"""

import io
import json
import sqlite3
import sys
from unittest.mock import MagicMock

import pytest

from aios.agents.developer import DeveloperAgent
from aios.agents.models import AgentResult
from aios.agents.planner import PlannerAgent
from aios.cli.commands import _cmd_plan
from aios.context import ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.events.events import (
    KANBAN_CARD_BLOCKED,
    KANBAN_CARD_MOVED,
    KANBAN_SUBTASK_COMPLETED,
    KANBAN_SUBTASK_CREATED,
)
from aios.memory import MemoryEngine
from aios.scheduler import KanbanEngine

INTENT = "e2e goal"


def _subtask(task_id: str, description: str) -> dict:
    return {
        "id": task_id,
        "description": description,
        "type": "code",
        "priority": "high",
        "dependencies": [],
        "estimated_complexity": "low",
    }


def _build_kernel(tmp_path, subtasks: list[dict], dev_results: list[AgentResult]):
    planner = PlannerAgent(runtime=None)
    developer = DeveloperAgent(runtime=None)
    plan = {"goal": INTENT, "subtasks": subtasks, "risks": [], "unknowns": []}
    planner.execute = MagicMock(
        return_value=AgentResult(success=True, output=json.dumps(plan), errors=[])
    )
    developer.execute = MagicMock(side_effect=dev_results)

    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.register(MemoryEngine(project_path=tmp_path))
    kernel.register(KanbanEngine(project_path=tmp_path))
    kernel.register(planner)
    kernel.register(developer)
    kernel.register(EventsEngine())
    return kernel


def _run_plan(kernel, stderr: io.StringIO) -> tuple[list, str]:
    real_start = kernel.start
    started = False

    def start_once():
        nonlocal started
        if not started:
            started = True
            real_start()

    kernel.start = start_once
    start_once()
    received = _collect_events(kernel)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stderr", stderr)
        _cmd_plan(["--run", INTENT], kernel.project_path, lambda _: kernel)
    return received, stderr.getvalue()


def _collect_events(kernel) -> list:
    bus = kernel.get_engine("events").bus
    received = []
    for topic in (
        KANBAN_CARD_MOVED,
        KANBAN_SUBTASK_CREATED,
        KANBAN_SUBTASK_COMPLETED,
        KANBAN_CARD_BLOCKED,
    ):
        bus.subscribe(topic, received.append)
    return received


def _load_kanban_cards(tmp_path) -> list[tuple]:
    db_path = tmp_path / ".aios" / "memory.db"
    assert db_path.exists(), "expected .aios/memory.db to be created"
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT title, column_name, tdd_gate, blocked FROM kanban_cards "
        "WHERE project_id=? ORDER BY id ASC",
        (str(tmp_path.resolve()),),
    ).fetchall()
    conn.close()
    return rows


def _exec_success(description: str) -> AgentResult:
    return AgentResult(success=True, output=f"Executed: {description}", errors=[])


def _exec_failure(description: str) -> AgentResult:
    return AgentResult(success=False, output="", errors=[f"Failed: {description}"])


def test_e2e_plan_run_all_cards_land_in_done(tmp_path):
    subtasks = [
        _subtask("1", "Add login"),
        _subtask("2", "Add tests"),
    ]
    kernel = _build_kernel(
        tmp_path,
        subtasks,
        [_exec_success("Add login"), _exec_success("Add tests")],
    )

    stderr = io.StringIO()
    received, output = _run_plan(kernel, stderr)
    kernel.shutdown()

    assert "Plano de Execução (2 tarefas):" in output
    assert "• Add login" in output

    rows = _load_kanban_cards(tmp_path)
    assert len(rows) == len(subtasks)
    assert all(column == "Done" for _, column, _, _ in rows)
    assert all(tdd_gate == 1 for _, _, tdd_gate, _ in rows)
    assert all(blocked == 0 for _, _, _, blocked in rows)

    topics = {event.topic for event in received}
    assert KANBAN_CARD_MOVED in topics
    assert KANBAN_SUBTASK_CREATED in topics
    assert KANBAN_SUBTASK_COMPLETED in topics
    assert KANBAN_CARD_BLOCKED not in topics


def test_e2e_plan_run_blocks_card_on_failure(tmp_path):
    subtasks = [
        _subtask("1", "First (ok)"),
        _subtask("2", "Second (fails)"),
    ]
    kernel = _build_kernel(
        tmp_path,
        subtasks,
        [_exec_success("First (ok)"), _exec_failure("Second (fails)")],
    )

    stderr = io.StringIO()
    received, output = _run_plan(kernel, stderr)
    kernel.shutdown()

    rows = _load_kanban_cards(tmp_path)
    assert len(rows) == len(subtasks)
    first = rows[0]
    second = rows[1]
    assert first[1] == "Done"
    assert first[2] == 1
    assert second[1] == "InProgress"
    assert second[3] == 1

    topics = {event.topic for event in received}
    assert KANBAN_CARD_BLOCKED in topics
