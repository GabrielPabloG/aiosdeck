"""Tests for aios quality stats CLI command."""

import json
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

from aios.core import Kernel
from aios.quality.cli import (
    _parse_filters,
    _render_records,
    _render_stats,
    cmd_quality_stats,
)
from aios.telemetry.engine import TelemetryEngine

_STAT = {
    "gate": "code_gate",
    "runs": 2,
    "passed": 1,
    "failed": 1,
    "skipped": 0,
    "errored": 0,
    "blocked": 1,
    "overridden": 0,
    "avg_duration_ms": 150.0,
    "findings_low": 0,
    "findings_medium": 0,
    "findings_high": 2,
    "findings_critical": 0,
}

_RECORD = {
    "id": 1,
    "gate": "code_gate",
    "status": "failed",
    "correlation_id": "run-1",
    "duration_ms": 120.0,
    "findings_low": 0,
    "findings_medium": 0,
    "findings_high": 1,
    "findings_critical": 0,
    "blocked": 1,
    "overridden": 0,
    "timestamp": "2026-01-01T00:00:00Z",
}


class TestParseFilters:
    def test_no_args(self):
        assert _parse_filters([]) == {"limit": 100}

    def test_json_flag(self):
        f = _parse_filters(["--json"])
        assert f["json"] is True
        assert f["limit"] == 100

    def test_gate_filter(self):
        f = _parse_filters(["--gate", "code_gate"])
        assert f["gate"] == "code_gate"

    def test_status_filter(self):
        f = _parse_filters(["--status", "blocked"])
        assert f["status"] == "blocked"

    def test_limit(self):
        f = _parse_filters(["--limit", "50"])
        assert f["limit"] == 50

    def test_records_flag(self):
        f = _parse_filters(["--records"])
        assert f["records"] is True

    def test_combined(self):
        f = _parse_filters(["--gate", "code_gate", "--json", "--limit", "10"])
        assert f["gate"] == "code_gate"
        assert f["json"] is True
        assert f["limit"] == 10

    def test_unknown_option(self):
        with suppress(SystemExit):
            _parse_filters(["--unknown"])


class TestRenderStats:
    def test_render_empty(self, capsys):
        _render_stats([])
        captured = capsys.readouterr()
        assert "No quality gate records found" in captured.out

    def test_render_with_data(self, capsys):
        _render_stats([_STAT])
        captured = capsys.readouterr()
        assert "Quality Gates" in captured.out
        assert "code_gate" in captured.out
        assert "2 runs" in captured.out
        assert "1 blocked" in captured.out
        assert "findings: low=0 medium=0 high=2 critical=0" in captured.out
        assert "avg duration: 150ms" in captured.out


class TestRenderRecords:
    def test_render_empty(self, capsys):
        _render_records([])
        captured = capsys.readouterr()
        assert "No quality gate records found" in captured.out

    def test_render_with_data(self, capsys):
        _render_records([_RECORD])
        captured = capsys.readouterr()
        assert "Quality Gate Records" in captured.out
        assert "code_gate" in captured.out
        assert "failed" in captured.out
        assert "blocked=1" in captured.out
        assert "overridden=0" in captured.out


def _telemetry(tmp_path):
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(tmp_path / "test.db"))
    engine.initialize()
    engine._store.insert_gate_record(
        {
            "gate": "code_gate",
            "status": "passed",
            "correlation_id": "run-1",
            "duration_ms": 100.0,
            "findings_low": 0,
            "findings_medium": 0,
            "findings_high": 0,
            "findings_critical": 0,
            "blocked": False,
            "overridden": False,
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )
    engine._store.insert_gate_record(
        {
            "gate": "code_gate",
            "status": "failed",
            "correlation_id": "run-2",
            "duration_ms": 120.0,
            "findings_low": 0,
            "findings_medium": 0,
            "findings_high": 1,
            "findings_critical": 0,
            "blocked": True,
            "overridden": False,
            "timestamp": "2026-01-02T00:00:00Z",
        }
    )
    return engine


def test_cmd_quality_stats_json(tmp_path, capsys):
    engine = _telemetry(tmp_path)
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(engine)
    with patch.object(kernel, "start", lambda: None):
        cmd_quality_stats(["--json", "--gate", "code_gate"], Path(tmp_path), lambda _: kernel)

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["gate"] == "code_gate"
    assert data[0]["runs"] == 2
    assert data[0]["passed"] == 1
    assert data[0]["failed"] == 1
    assert data[0]["blocked"] == 1
    engine.shutdown()


def test_cmd_quality_stats_records_json(tmp_path, capsys):
    engine = _telemetry(tmp_path)
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(engine)
    with patch.object(kernel, "start", lambda: None):
        cmd_quality_stats(["--records", "--json"], Path(tmp_path), lambda _: kernel)

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    assert data[0]["gate"] == "code_gate"
    assert data[0]["blocked"] == 1
    engine.shutdown()


def test_cmd_quality_stats_unavailable_engine(tmp_path, capsys):
    kernel = Kernel(project_path=str(tmp_path))
    with patch.object(kernel, "start", lambda: None):
        cmd_quality_stats([], Path(tmp_path), lambda _: kernel)
    assert "not available" in capsys.readouterr().out
