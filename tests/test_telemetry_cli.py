"""Tests for aios usage CLI command."""

from contextlib import suppress
from pathlib import Path
from unittest.mock import MagicMock, patch

from aios.core import Kernel
from aios.telemetry.cli import _parse_filters, _render_table, cmd_usage
from aios.telemetry.engine import TelemetryEngine


class TestParseFilters:
    def test_no_args(self):
        assert _parse_filters([]) == {"limit": 100}

    def test_json_flag(self):
        f = _parse_filters(["--json"])
        assert f["json"] is True
        assert f["limit"] == 100

    def test_agent_filter(self):
        f = _parse_filters(["--agent", "planner"])
        assert f["agent"] == "planner"

    def test_model_filter(self):
        f = _parse_filters(["--model", "gpt-4o"])
        assert f["model"] == "gpt-4o"

    def test_today(self):
        f = _parse_filters(["--today"])
        assert "date_from" in f
        assert "date_to" in f

    def test_workflow(self):
        f = _parse_filters(["--workflow", "wf-001"])
        assert f["workflow_id"] == "wf-001"

    def test_date_range(self):
        f = _parse_filters(["--from", "2026-01-01", "--to", "2026-01-31"])
        assert f["date_from"] == "2026-01-01"
        assert f["date_to"] == "2026-01-31"

    def test_limit(self):
        f = _parse_filters(["--limit", "50"])
        assert f["limit"] == 50

    def test_combined_filters(self):
        f = _parse_filters(
            [
                "--agent",
                "planner",
                "--model",
                "gpt-4o",
                "--json",
                "--limit",
                "200",
            ]
        )
        assert f["agent"] == "planner"
        assert f["model"] == "gpt-4o"
        assert f["json"] is True
        assert f["limit"] == 200

    def test_unknown_option(self):
        with suppress(SystemExit):
            _parse_filters(["--unknown"])


class TestRenderTable:
    def test_render_empty_data(self, capsys):
        data = {
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost": 0,
                "currency": "USD",
            },
            "by_agent": {},
            "by_model": {},
            "records": [],
            "cost_records": [],
            "executions": [],
        }
        _render_table(data)
        captured = capsys.readouterr()
        assert "No usage records found" in captured.out

    def test_render_deferred_token_tracking_shows_executions(self, capsys):
        data = {
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_cost": 0,
                "currency": "USD",
            },
            "by_agent": {},
            "by_model": {},
            "records": [],
            "cost_records": [],
            "executions": [
                {
                    "execution_id": "exec-1",
                    "agent": "planner",
                    "status": "succeeded",
                },
                {
                    "execution_id": "exec-2",
                    "agent": "developer",
                    "status": "succeeded",
                },
            ],
        }
        _render_table(data)
        captured = capsys.readouterr()
        assert "No token usage recorded" in captured.out
        assert "token tracking deferred" in captured.out
        assert "2 execution(s) recorded" in captured.out
        assert "No usage records found" not in captured.out

    def test_render_with_data(self, capsys):
        data = {
            "totals": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "total_cost": 0.0013,
                "currency": "USD",
            },
            "by_agent": {
                "planner": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "count": 1,
                }
            },
            "by_model": {
                "gpt-4o": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "count": 1,
                }
            },
            "records": [
                {
                    "execution_id": "exec-1",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "agent": "planner",
                    "model": "gpt-4o",
                },
            ],
            "cost_records": [
                {"execution_id": "exec-1", "status": "priced", "total_cost": 0.0013},
            ],
        }
        _render_table(data)
        captured = capsys.readouterr()
        assert "Total input tokens" in captured.out
        assert "planner" in captured.out.lower()
        assert "gpt-4o" in captured.out.lower()
        assert "1 usage record" in captured.out

    def test_render_unpriced(self, capsys):
        data = {
            "totals": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "total_cost": 0,
                "currency": "USD",
            },
            "by_agent": {},
            "by_model": {},
            "records": [
                {
                    "execution_id": "exec-1",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "agent": "test",
                }
            ],
            "cost_records": [
                {"execution_id": "exec-1", "status": "unpriced"},
            ],
        }
        _render_table(data)
        captured = capsys.readouterr()
        assert "Unpriced" in captured.out


def test_cmd_usage_json_output(tmp_path, capsys):
    db = tmp_path / "test.db"

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "agent": "planner",
        "status": "succeeded",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "model": "gpt-4o",
            "provider": "openai",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }
    engine._on_execution_event(event)

    result = engine.query()
    assert result["totals"]["input_tokens"] == 100

    engine.shutdown()


def test_cmd_usage_unavailable_engine(tmp_path, capsys):
    kernel = Kernel(project_path=str(tmp_path))
    with patch.object(kernel, "start", lambda: None):
        cmd_usage([], Path(tmp_path), lambda p: kernel)
