"""Tests for skills CLI — discover, inspect, stats."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from aios.skills.cli import cmd_skills_discover, cmd_skills_inspect, cmd_skills_stats


def _make_kernel(knowledge=None, telemetry=None, context=None):
    kernel = MagicMock()
    kernel.get_context.return_value = context
    kernel.get_engine.side_effect = lambda name: {
        "knowledge": knowledge,
        "telemetry": telemetry,
    }.get(name)
    return kernel


def _kernel_factory(kernel):
    def factory(project_path):
        kernel.project_path = project_path
        return kernel

    return factory


def _write_skill(project_path: Path, name: str, triggers: str = "test") -> None:
    skills_dir = project_path / ".opencode" / "skills" / name
    skills_dir.mkdir(parents=True)
    content = f"---\nname: {name}\ndescription: A test skill\ntriggers:\n  - {triggers}\n---\n\n# {name}\n\nContent."
    (skills_dir / "SKILL.md").write_text(content)


class TestSkillsDiscover:
    def test_usage_when_no_args(self, capsys):
        kernel = _make_kernel()
        factory = _kernel_factory(kernel)
        try:
            cmd_skills_discover([], Path("/tmp"), factory)
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "Usage:" in captured.err

    def test_discover_json_output(self, tmp_path, capsys):
        _write_skill(tmp_path, "test-skill", "react")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_discover(
                ["build a react dashboard", "--json", "--top", "3"],
                tmp_path,
                factory,
            )
        except SystemExit:
            pass

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["intent"] == "build a react dashboard"
        assert "skills" in output
        assert len(output["skills"]) > 0
        assert output["skills"][0]["name"] == "test-skill"

    def test_discover_no_matches(self, tmp_path, capsys):
        _write_skill(tmp_path, "only-python", "python")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_discover(
                ["deploy docker containers"],
                tmp_path,
                factory,
            )
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "No skills matched" in captured.out or "No skills matched" in captured.err


class TestSkillsInspect:
    def test_inspect_found(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "python")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect(["my-skill"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "my-skill" in captured.out
        assert "A test skill" in captured.out

    def test_inspect_json_output(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "python")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect(["my-skill", "--json"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["name"] == "my-skill"

    def test_inspect_not_found(self, tmp_path, capsys):
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect(["nonexistent"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "not found" in captured.out or "not found" in captured.err

    def test_inspect_usage_no_args(self, capsys):
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect([], Path("/tmp"), factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "Usage:" in captured.err


class TestSkillsStats:
    def test_stats_empty(self, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = []
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats([], Path("/tmp"), factory)

        captured = capsys.readouterr()
        assert "No skill usage records found." in captured.out

    def test_stats_json_output(self, capsys):
        data = [
            {
                "skill_name": "test-skill",
                "total_records": 5,
                "total_considered": 5,
                "total_selected": 3,
                "total_used": 2,
                "avg_relevance": 0.75,
                "total_tokens": 500,
            }
        ]
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = data
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats(["--json"], Path("/tmp"), factory)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output[0]["skill_name"] == "test-skill"
        assert output[0]["total_used"] == 2

    def test_stats_with_filter(self, capsys):
        data = [
            {
                "skill_name": "s",
                "total_records": 1,
                "total_considered": 1,
                "total_selected": 1,
                "total_used": 1,
                "avg_relevance": 0.8,
                "total_tokens": 100,
            }
        ]
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = data
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats(["--skill", "s"], Path("/tmp"), factory)

        captured = capsys.readouterr()
        assert "s" in captured.out

    def test_stats_no_telemetry(self, capsys):
        kernel = _make_kernel()
        factory = _kernel_factory(kernel)
        cmd_skills_stats([], Path("/tmp"), factory)
        captured = capsys.readouterr()
        assert "Telemetry engine not available." in captured.out

    def test_stats_table_headers(self, capsys):
        data = [
            {
                "skill_name": "test-skill",
                "total_records": 5,
                "total_considered": 5,
                "total_selected": 3,
                "total_used": 2,
                "avg_relevance": 0.75,
                "total_tokens": 500,
            }
        ]
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = data
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats([], Path("/tmp"), factory)

        captured = capsys.readouterr()
        assert "Skill Stats" in captured.out
        assert "Skill" in captured.out
        assert "Used" in captured.out
        assert "Selected" in captured.out
        assert "Considered" in captured.out
        assert "AvgScore" in captured.out
        assert "Tokens" in captured.out
        assert "1 skill(s)" in captured.out

    def test_stats_with_date_from_to(self, capsys):
        data = [
            {
                "skill_name": "s",
                "total_records": 1,
                "total_considered": 1,
                "total_selected": 1,
                "total_used": 1,
                "avg_relevance": 0.5,
                "total_tokens": 10,
            }
        ]
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = data
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats(["--from", "2026-01-01", "--to", "2026-12-31"], Path("/tmp"), factory)

        telemetry.query_skill_stats.assert_called_once_with(
            skill=None, date_from="2026-01-01", date_to="2026-12-31"
        )

    def test_stats_with_today_flag(self, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = []
        kernel = _make_kernel(telemetry=telemetry)
        factory = _kernel_factory(kernel)

        cmd_skills_stats(["--today"], Path("/tmp"), factory)

        call_kwargs = telemetry.query_skill_stats.call_args[1]
        assert call_kwargs["date_from"] is not None
        assert call_kwargs["date_from"].endswith("T00:00:00")

    def test_stats_zero_relevance_uses_dash_and_ignores_agent_filter(self, capsys):
        telemetry = MagicMock()
        telemetry.query_skill_stats.return_value = [
            {
                "skill_name": "zero",
                "total_records": 1,
                "total_considered": 1,
                "total_selected": 0,
                "total_used": 0,
                "avg_relevance": 0,
                "total_tokens": 0,
            }
        ]
        kernel = _make_kernel(telemetry=telemetry)

        cmd_skills_stats(["--agent", "developer"], Path("/tmp"), _kernel_factory(kernel))

        assert "—" in capsys.readouterr().out
        telemetry.query_skill_stats.assert_called_once_with(
            skill=None, date_from=None, date_to=None
        )


class TestSkillsDiscoverNonJson:
    def test_discover_non_json_with_matches(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "react")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_discover(["build a react dashboard"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "Skill Discovery" in captured.out
        assert "Intent:" in captured.out
        assert "Agent:" in captured.out
        assert "Candidates:" in captured.out
        assert "my-skill" in captured.out

    def test_discover_with_agent_flag(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "react")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_discover(
                ["build react", "--agent", "developer", "--top", "1"],
                tmp_path,
                factory,
            )
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "developer" in captured.out


class TestSkillsInspectExactStrings:
    def test_inspect_exact_field_labels(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "python")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect(["my-skill"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        assert "Skill: my-skill" in captured.out
        assert "Description" in captured.out
        assert "Status" in captured.out
        assert "Priority" in captured.out
        assert "Version" in captured.out
        assert "Triggers" in captured.out
        assert "Indexed" in captured.out

    def test_inspect_json_has_all_fields(self, tmp_path, capsys):
        _write_skill(tmp_path, "my-skill", "python")
        kernel = _make_kernel()
        kernel.get_context.return_value = None
        factory = _kernel_factory(kernel)

        try:
            cmd_skills_inspect(["my-skill", "--json"], tmp_path, factory)
        except SystemExit:
            pass

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "name" in output
        assert "description" in output
        assert "triggers" in output
        assert "scope" in output
        assert "dependencies" in output
        assert "priority" in output
        assert "version" in output
        assert "owner" in output
        assert "updated_at" in output
        assert "status" in output
        assert "schema_version" in output
        assert "indexed" in output
        assert "chunks_count" in output
