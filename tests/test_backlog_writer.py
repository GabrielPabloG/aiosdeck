"""Tests for backlog_writer — TODO.md output format and atomic writes."""

import tempfile
from pathlib import Path

from aios.scheduler.backlog_writer import write_backlog


def _read_todo(path: Path) -> list[str]:
    return path.read_text().splitlines()


def test_write_backlog_empty():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    result = write_backlog([], output_path=tmp)
    assert result == tmp
    assert result.read_text() == ""


def test_write_backlog_header_and_checkboxes():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    tasks = [
        {"title": "Add login", "checked": True},
        {"title": "Add tests", "checked": False},
        {"title": "Deploy", "checked": False},
    ]
    write_backlog(tasks, output_path=tmp)

    lines = _read_todo(tmp)
    assert lines[0] == "# Backlog (3)"
    assert lines[1] == ""
    assert lines[2] == "- [X] Add login"
    assert lines[3] == "- [ ] Add tests"
    assert lines[4] == "- [ ] Deploy"


def test_write_backlog_spinner_for_active_index():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    tasks = [
        {"title": "Task A", "checked": True},
        {"title": "Task B", "checked": False},
        {"title": "Task C", "checked": False},
    ]
    write_backlog(tasks, active_index=2, output_path=tmp)

    lines = _read_todo(tmp)
    assert lines[0] == "# Backlog (3)"
    assert lines[2] == "- [X] Task A"
    assert lines[3] == "- *(spinner) Task B…"
    assert lines[4] == "- [ ] Task C"


def test_write_backlog_active_index_1():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    tasks = [{"title": "First", "checked": False}]
    write_backlog(tasks, active_index=1, output_path=tmp)

    lines = _read_todo(tmp)
    assert lines[0] == "# Backlog (1)"
    assert lines[2] == "- *(spinner) First…"


def test_write_backlog_active_none_after_all_done():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    tasks = [
        {"title": "Task 1", "checked": True},
        {"title": "Task 2", "checked": True},
    ]
    write_backlog(tasks, active_index=None, output_path=tmp)

    lines = _read_todo(tmp)
    assert lines[0] == "# Backlog (2)"
    assert lines[2] == "- [X] Task 1"
    assert lines[3] == "- [X] Task 2"


def test_write_backlog_atomic_write():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    tmp.write_text("old content")

    tasks = [{"title": "New task", "checked": False}]
    write_backlog(tasks, output_path=tmp)

    content = tmp.read_text()
    assert "# Backlog (1)" in content
    assert "old content" not in content


def test_write_backlog_returns_path():
    tmp = Path(tempfile.mkdtemp()) / "TODO.md"
    result = write_backlog([{"title": "X", "checked": True}], output_path=tmp)
    assert result == tmp


def test_write_backlog_subdirectory(tmp_path):
    out = tmp_path / "sub" / "TODO.md"
    write_backlog([{"title": "Deep", "checked": False}], output_path=out)
    assert out.exists()
    lines = out.read_text().splitlines()
    assert lines[0] == "# Backlog (1)"
