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
        assert "No skill usage" in captured.out

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
        assert "not available" in captured.out
