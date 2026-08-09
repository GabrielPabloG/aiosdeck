"""Tests for backlog parser — conventional commit parsing and task loading."""

from pathlib import Path

from aios.backlog.parser import (
    load_tasks_from_file,
    load_tasks_from_kanban,
    parse_conventional,
)


class _FakeKanbanCard:
    def __init__(self, title: str, column: str):
        self.title = title
        self.column = column


class _FakeKanbanBoard:
    def __init__(self, name: str, id: int = 1):
        self.name = name
        self.id = id


class _FakeKanbanEngine:
    def __init__(self, boards=None, cards=None):
        self._boards = boards or [_FakeKanbanBoard("backlog")]
        self._cards = cards or []

    def list_boards(self):
        return self._boards

    def list_cards(self, board_id: int):
        return self._cards


class TestParseConventional:
    def test_full_with_scope_and_version(self):
        typ, scope, subject, version = parse_conventional(
            "feat(backlog): add task models (v0.9.13)"
        )
        assert typ == "feat"
        assert scope == "backlog"
        assert subject == "add task models"
        assert version == "v0.9.13"

    def test_with_scope_no_version(self):
        typ, scope, subject, version = parse_conventional("fix(core): handle null pointer")
        assert typ == "fix"
        assert scope == "core"
        assert subject == "handle null pointer"
        assert version == ""

    def test_no_scope_no_version(self):
        typ, scope, subject, version = parse_conventional("chore: bump version")
        assert typ == "chore"
        assert scope == ""
        assert subject == "bump version"
        assert version == ""

    def test_invalid_title(self):
        assert parse_conventional("just some text") == ("", "", "", "")

    def test_with_version_no_scope(self):
        typ, scope, subject, version = parse_conventional(
            "chore(release): bump version to 0.9.13 (v0.9.13)"
        )
        assert typ == "chore"
        assert scope == "release"
        assert subject == "bump version to 0.9.13"
        assert version == "v0.9.13"

    def test_title_with_colon_no_match(self):
        assert parse_conventional("noise:") == ("", "", "", "")

    def test_multiline_ignores_newlines(self):
        typ, scope, subject, version = parse_conventional("feat: add feature (v1.0.0)")
        assert typ == "feat"
        assert version == "v1.0.0"

    def test_scope_with_dashes(self):
        typ, scope, subject, version = parse_conventional("fix(ui-components): button alignment")
        assert typ == "fix"
        assert scope == "ui-components"
        assert subject == "button alignment"


class TestLoadTasksFromFile:
    def test_basic(self, tmp_path: Path):
        todo = tmp_path / "TODO.md"
        todo.write_text(
            "- [ ] feat(backlog): add models (v0.9.13)\n"
            "- [ ] fix(core): handle null\n"
            "- [X] already done\n"
            "- [ ] chore: release (v0.9.13)\n"
        )
        tasks = load_tasks_from_file(todo)
        assert len(tasks) == 3
        assert tasks[0].type == "feat"
        assert tasks[0].scope == "backlog"
        assert tasks[0].subject == "add models"
        assert tasks[0].version == "v0.9.13"
        assert tasks[1].type == "fix"
        assert tasks[1].scope == "core"
        assert tasks[2].type == "chore"
        assert tasks[2].version == "v0.9.13"

    def test_non_existent_file(self):
        tasks = load_tasks_from_file("/nonexistent/todo.md")
        assert tasks == []

    def test_empty_file(self, tmp_path: Path):
        todo = tmp_path / "empty.md"
        todo.write_text("")
        assert load_tasks_from_file(todo) == []

    def test_no_tasks_lines(self, tmp_path: Path):
        todo = tmp_path / "notes.md"
        todo.write_text("# Notes\n\nSome text without checkboxes.\n")
        assert load_tasks_from_file(todo) == []


class TestLoadTasksFromKanban:
    def test_basic(self):
        cards = [
            _FakeKanbanCard("feat(backlog): add models (v0.9.13)", "Todo"),
            _FakeKanbanCard("fix(core): handle null", "Todo"),
            _FakeKanbanCard("chore: release (v0.9.13)", "Done"),
        ]
        engine = _FakeKanbanEngine(cards=cards)
        tasks = load_tasks_from_kanban(engine, "backlog")
        assert len(tasks) == 2
        assert tasks[0].type == "feat"
        assert tasks[0].scope == "backlog"
        assert tasks[0].subject == "add models"
        assert tasks[1].type == "fix"

    def test_board_not_found(self):
        engine = _FakeKanbanEngine(boards=[])
        tasks = load_tasks_from_kanban(engine, "nonexistent")
        assert tasks == []

    def test_no_cards(self):
        engine = _FakeKanbanEngine(cards=[])
        tasks = load_tasks_from_kanban(engine, "backlog")
        assert tasks == []

    def test_unconventional_titles_default_to_feat(self):
        cards = [
            _FakeKanbanCard("some random task", "Todo"),
        ]
        engine = _FakeKanbanEngine(cards=cards)
        tasks = load_tasks_from_kanban(engine, "backlog")
        assert len(tasks) == 1
        assert tasks[0].type == "feat"
        assert tasks[0].subject == "some random task"
