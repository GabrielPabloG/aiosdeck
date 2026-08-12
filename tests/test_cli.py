import json
import subprocess
from unittest.mock import MagicMock, patch

from aios.cli.commands.exec_cmds import (
    _gate_label,
    _gates_json,
    _render_gate_trail,
    _render_stage,
    _run_result_to_json,
    cmd_plan,
)
from aios.core.run_result import RunResult, StageSummary
from aios.quality.contracts import GateFinding, Severity


def test_help():
    result = subprocess.run(["aios", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_help_command():
    result = subprocess.run(["aios", "help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_no_args_shows_dashboard():
    result = subprocess.run(["aios"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_invalid_command():
    result = subprocess.run(["aios", "nonexistent"], capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_start_alias():
    result = subprocess.run(
        ["aios", "start", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_status_alias():
    result = subprocess.run(
        ["aios", "status", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "AiosDeck" in output


def test_doctor():
    result = subprocess.run(
        ["aios", "doctor", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_doctor_json():
    result = subprocess.run(
        ["aios", "doctor", "--json", "examples/hello-python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert '"project"' in result.stdout
    assert '"engines"' in result.stdout


def test_memory_list(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "list"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_memory_add_convention(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "add", "convention", "Use snake_case"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Convention saved" in result.stdout or "convention saved" in result.stdout.lower()


def test_memory_add_unknown_type(tmp_path):
    result = subprocess.run(
        ["aios", "memory", "add", "invalid", "something"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Unknown type" in result.stdout


def test_memory_forget(tmp_path):
    subprocess.run(
        ["aios", "memory", "add", "convention", "ToDelete"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    result = subprocess.run(
        ["aios", "memory", "forget", "convention", "ToDelete"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_memory_search(tmp_path):
    subprocess.run(
        ["aios", "memory", "add", "convention", "UseSnakeCase"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    result = subprocess.run(
        ["aios", "memory", "search", "Snake"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0


def test_completion_top_level():
    result = subprocess.run(
        ["aios", "__complete", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "doctor" in result.stdout
    assert "memory" in result.stdout
    assert "help" in result.stdout


def test_completion_memory_subcommands():
    result = subprocess.run(
        ["aios", "__complete", "", "memory"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "add" in result.stdout
    assert "forget" in result.stdout
    assert "list" in result.stdout
    assert "search" in result.stdout


def test_completion_memory_add_types():
    result = subprocess.run(
        ["aios", "__complete", "", "memory", "add"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "convention" in result.stdout
    assert "decision" in result.stdout


def test_completion_partial():
    result = subprocess.run(
        ["aios", "__complete", "m", ""],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "memory" in result.stdout


def test_completion_command_bash():
    result = subprocess.run(
        ["aios", "completion", "--bash"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "complete -F _aios_completion aios aiosdeck ad" in result.stdout
    assert "_aios_completion()" in result.stdout


def test_completion_command_zsh():
    result = subprocess.run(
        ["aios", "completion", "--zsh"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "#compdef aios aiosdeck ad" in result.stdout
    assert "compdef _aios_completion aios aiosdeck ad" in result.stdout


def test_completion_command_requires_shell():
    result = subprocess.run(
        ["aios", "completion"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Usage:" in result.stderr


def test_research_web_without_fetcher(tmp_path):
    result = subprocess.run(
        ["aios", "research", "auth flow", "--scope", "web"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "source_unavailable" in output


def test_research_json(tmp_path):
    result = subprocess.run(
        ["aios", "research", "auth flow", "--scope", "web", "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "source_unavailable"
    assert data["findings"] == []
    assert data["sources"] == []


def test_research_repo_scope(tmp_path):
    (tmp_path / "health.py").write_text(
        "def health_check():\n    return True\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["aios", "research", "health check", "--scope", "repo"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "status: ok" in output
    assert "Findings" in output


def test_research_output_file(tmp_path):
    out = tmp_path / "report.json"
    result = subprocess.run(
        ["aios", "research", "auth flow", "--scope", "web", "--output", str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "source_unavailable"


# ---------------------------------------------------------------------------
# Quality gate trail rendering (plan --run)
# ---------------------------------------------------------------------------


def _stage(name, status="success", details=None, reason=None) -> StageSummary:
    return StageSummary(name=name, status=status, reason=reason, details=details or {})


def _gate_details(status, findings=None, policy=None, skipped=False) -> dict:
    details = {"gate": {"status": status, "reason": "r", "findings": findings or []}}
    if skipped:
        details["skipped"] = True
    if policy:
        details["policy"] = policy
    return details


def test_gate_label_passed():
    label, detail = _gate_label(_stage("code_gate", details=_gate_details("passed")))
    assert label == "PASS"
    assert detail == ""


def test_gate_label_failed_block():
    stage = _stage(
        "code_gate",
        status="failed",
        reason="blocking severity: high",
        details=_gate_details("failed", policy={"decision": "block"}),
    )
    label, detail = _gate_label(stage)
    assert label == "FAIL"
    assert "blocking severity: high" in detail


def test_gate_label_skipped():
    label, detail = _gate_label(
        _stage("security_gate", status="skipped", details=_gate_details("skipped", skipped=True))
    )
    assert label == "SKIP"
    assert detail == "(skipped)"


def test_gate_label_warn():
    stage = _stage(
        "code_gate",
        status="success",
        details=_gate_details("failed", policy={"decision": "warn"}),
    )
    label, detail = _gate_label(stage)
    assert label == "PASS"
    assert "(warn)" in detail


def test_gate_label_override():
    stage = _stage(
        "code_gate",
        status="success",
        details=_gate_details(
            "failed",
            policy={"decision": "block", "overridden": True, "override_reason": "manual ok"},
        ),
    )
    label, detail = _gate_label(stage)
    assert label == "PASS"
    assert "override: manual ok" in detail


def test_gates_json_complete_findings():
    finding = GateFinding(
        id="F1", title="unused import", severity=Severity.HIGH, category="lint"
    ).to_dict()
    stage = _stage(
        "code_gate",
        status="failed",
        reason="blocking severity: high",
        details=_gate_details("failed", findings=[finding], policy={"decision": "block"}),
    )
    result = RunResult(success=False, stages=(_stage("developer:1"), stage), errors=("x",))
    gates = _gates_json(result)
    assert list(gates) == ["code_gate"]
    assert gates["code_gate"]["status"] == "failed"
    assert gates["code_gate"]["findings"] == [finding]
    assert gates["code_gate"]["policy"] == {"decision": "block"}


def test_run_result_to_json_shape():
    result = RunResult(success=True, stages=(), errors=())
    assert _run_result_to_json(result) == {"success": True, "errors": [], "gates": {}}


def test_render_gate_trail_human(capsys):
    stages = (
        _stage("code_gate", details=_gate_details("passed")),
        _stage("security_gate", status="skipped", details=_gate_details("skipped", skipped=True)),
        _stage(
            "documentation_gate",
            status="failed",
            reason="blocking severity: high",
            details=_gate_details("failed", policy={"decision": "block"}),
        ),
    )
    _render_gate_trail(RunResult(success=False, stages=stages, errors=()))
    out = capsys.readouterr().err
    assert "Quality Gates:" in out
    assert "[PASS] code_gate" in out
    assert "[SKIP] security_gate" in out
    assert "[FAIL] documentation_gate" in out


def test_render_gate_trail_empty_when_no_gates(capsys):
    _render_gate_trail(RunResult(success=True, stages=(_stage("planner"),), errors=()))
    assert capsys.readouterr().err == ""


def test_render_stage_keeps_permanent_lines(capsys):
    stage = StageSummary(name="developer:1", status="success", details={"description": "task a"})
    _render_stage(stage)
    captured = capsys.readouterr()
    assert "[✓] task a" in captured.out


def test_plan_run_uses_progress_bar(tmp_path):
    with patch("aios.cli.commands.exec_cmds.ProgressBar") as mock_bar_cls:
        mock_bar = MagicMock()
        mock_bar_cls.return_value = mock_bar

        mock_kernel = MagicMock()
        mock_kernel.get_context.return_value = None
        mock_kernel.run.return_value = RunResult(success=True, stages=())

        cmd_plan(["--run", "test task"], tmp_path, lambda _: mock_kernel)

        assert mock_bar_cls.called


def test_plan_run_json_stdout_clean(tmp_path, capsys):
    with patch("aios.cli.commands.exec_cmds.ProgressBar"):
        mock_kernel = MagicMock()
        mock_kernel.get_context.return_value = None
        stages = (StageSummary(name="planner", status="success"),)
        mock_kernel.run.return_value = RunResult(success=True, stages=stages)

        cmd_plan(["--run", "test", "--json"], tmp_path, lambda pp: mock_kernel)
        out_text = capsys.readouterr().out
        report = json.loads(out_text)
        assert report["success"] is True


def test_plan_planning_uses_indeterminate_bar(tmp_path):
    with patch("aios.cli.commands.exec_cmds.ProgressBar") as mock_bar_cls:
        mock_bar = MagicMock()
        mock_bar_cls.return_value = mock_bar

        mock_kernel = MagicMock()
        mock_kernel.get_context.return_value = None
        mock_kernel.run.return_value = RunResult(success=True, stages=())

        cmd_plan(["plan test task"], tmp_path, lambda _: mock_kernel)

        assert mock_bar_cls.called
