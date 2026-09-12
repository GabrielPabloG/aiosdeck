import json
import subprocess
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Doctor command — direct function tests with exact string assertions
# ---------------------------------------------------------------------------


def test_doctor_direct_json_output(capsys):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    kernel.status.return_value = {
        "project": "/test",
        "engines": {"telemetry": "ready"},
        "errors": [],
    }
    kernel.get_context.return_value = None

    def factory(_path):
        return kernel

    cmd_doctor(["--json"], Path("/tmp"), factory)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["project"] == "/test"
    assert "engines" in data
    assert data["engines"]["telemetry"] == "ready"


def test_doctor_direct_with_context(capsys):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    ctx = MagicMock()
    ctx.project.language = "python"
    ctx.tools.linter = "ruff"
    ctx.tools.formatter = "ruff"
    ctx.tools.test_runner = "pytest"
    ctx.git.branch = "main"
    ctx.git.status = "clean"
    ctx.runtime.opencode = True
    ctx.runtime.ai_jail = False
    kernel.get_context.return_value = ctx
    kernel.status.return_value = {
        "project": "/test",
        "engines": {},
        "errors": [],
    }

    def factory(_path):
        return kernel

    cmd_doctor([], Path("/tmp"), factory)


def test_doctor_direct_with_diagnostics(capsys):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    kernel.get_context.return_value = None
    kernel.status.return_value = {
        "project": "/test",
        "engines": {},
        "errors": ["something broke"],
        "runtime_diagnostics": {
            "status": "ready",
            "code": "ok",
            "provider": "openai",
            "model": "gpt-4o",
            "source": "config",
            "suggestions": ["try restarting"],
        },
    }

    def factory(_path):
        return kernel

    cmd_doctor([], Path("/tmp"), factory)


def test_doctor_direct_no_diagnostics(capsys):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    kernel.get_context.return_value = None
    kernel.status.return_value = {
        "project": "/test",
        "engines": {},
        "errors": [],
    }

    def factory(_path):
        return kernel

    cmd_doctor([], Path("/tmp"), factory)


# ---------------------------------------------------------------------------
# Init command — direct function tests
# ---------------------------------------------------------------------------


def test_init_creates_project_yaml(tmp_path):
    from aios.cli.commands.core import cmd_init

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_init([], tmp_path, factory)

    yaml_path = tmp_path / ".aios" / "project.yaml"
    assert yaml_path.exists()
    content = yaml_path.read_text()
    assert "runtime: opencode" in content
    assert "sandbox: ai-jail" in content
    assert "project-dna" in content
    assert "coding-style" in content


def test_init_idempotent(tmp_path):
    from aios.cli.commands.core import cmd_init

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_init([], tmp_path, factory)
    first_content = (tmp_path / ".aios" / "project.yaml").read_text()
    cmd_init([], tmp_path, factory)
    second_content = (tmp_path / ".aios" / "project.yaml").read_text()
    assert first_content == second_content


def test_init_adds_gitignore_rule(tmp_path):
    from aios.cli.commands.core import cmd_init

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_init([], tmp_path, factory)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert ".aios/memory.db" in gitignore


def test_init_skips_existing_gitignore_rule(tmp_path):
    from aios.cli.commands.core import cmd_init

    (tmp_path / ".gitignore").write_text(".aios/memory.db\n")
    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_init([], tmp_path, factory)
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(".aios/memory.db") == 1


# ---------------------------------------------------------------------------
# Completion command — direct function tests
# ---------------------------------------------------------------------------


def test_completion_bash_direct(capsys):
    from aios.cli.commands.core import cmd_completion

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_completion(["--bash"], Path("/tmp"), factory)
    out = capsys.readouterr().out
    assert "complete -F _aios_completion aios aiosdeck ad" in out
    assert "_aios_completion()" in out


def test_completion_zsh_direct(capsys):
    from aios.cli.commands.core import cmd_completion

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_completion(["--zsh"], Path("/tmp"), factory)
    out = capsys.readouterr().out
    assert "#compdef aios aiosdeck ad" in out


def test_completion_no_flag_exits(capsys):
    from aios.cli.commands.core import cmd_completion

    kernel = MagicMock()

    def factory(_path):
        return kernel

    try:
        cmd_completion([], Path("/tmp"), factory)
    except SystemExit as e:
        assert e.code == 1
    err = capsys.readouterr().err
    assert "Usage: aios completion --bash | --zsh" in err


# ---------------------------------------------------------------------------
# Help command — exact string assertions
# ---------------------------------------------------------------------------


def test_help_exact_strings(capsys):
    from aios.cli.commands.core import cmd_help

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_help([], Path("/tmp"), factory)
    out = capsys.readouterr().out
    assert "AiosDeck" in out
    assert "The AI Operating System for Developers" in out


# ---------------------------------------------------------------------------
# Exit command
# ---------------------------------------------------------------------------


def test_exit_calls_kernel_shutdown():
    from aios.cli.commands.core import cmd_exit

    kernel = MagicMock()

    def factory(_path):
        return kernel

    cmd_exit([], Path("/tmp"), factory)
    kernel.shutdown.assert_called_once()


def test_doctor_json_includes_context_fields(capsys):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    context = MagicMock()
    context.project.language = "python"
    context.tools.linter = "ruff"
    context.tools.formatter = "ruff"
    context.tools.test_runner = "pytest"
    context.git.branch = "main"
    context.git.status = "clean"
    context.runtime.opencode = True
    context.runtime.ai_jail = False
    kernel.get_context.return_value = context
    kernel.status.return_value = {"project": "/repo", "engines": {}, "errors": []}

    def factory(_path):
        return kernel

    cmd_doctor(["--json"], Path("/tmp"), factory)
    data = json.loads(capsys.readouterr().out)
    assert data["context"] == {
        "language": "python",
        "linter": "ruff",
        "formatter": "ruff",
        "test_runner": "pytest",
        "git_branch": "main",
        "git_status": "clean",
        "opencode": True,
        "ai_jail": False,
    }
    kernel.start.assert_called_once_with()
    kernel.diagnose_runtime.assert_called_once_with()


def test_doctor_logs_diagnostics_suggestions_and_warnings(caplog):
    from aios.cli.commands.core import cmd_doctor

    kernel = MagicMock()
    kernel.get_context.return_value = None
    kernel.status.return_value = {
        "project": "/repo",
        "engines": {},
        "runtime_diagnostics": {
            "status": "degraded",
            "code": "runtime_error",
            "provider": "",
            "model": "",
            "source": "config",
            "suggestions": ["check runtime", "retry"],
        },
        "errors": ["runtime unavailable"],
    }

    def factory(_path):
        return kernel

    with caplog.at_level("INFO", logger="aios"):
        cmd_doctor([], Path("/tmp"), factory)

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "Runtime Diagnostics" in output
    assert "Status" in output
    assert "runtime_error" in output
    assert "not configured" in output
    assert "Suggestion" in output
    assert "check runtime" in output
    assert "retry" in output
    assert "Warnings:" in output
    assert "runtime unavailable" in output


def test_help_lists_every_public_command_and_alias_section(capsys):
    from aios.cli.commands import _print_help

    _print_help()
    output = capsys.readouterr().out
    expected = (
        "Usage:",
        "aios doctor",
        "aios memory",
        "aios plan",
        "aios review",
        "aios research",
        "aios usage",
        "aios benchmark",
        "aios quality",
        "aios policy",
        "aios security",
        "aios knowledge",
        "aios skills",
        "aios learning",
        "aios ocean",
        "aios route",
        "aios backlog",
        "aios help",
        "aios completion",
        "Commands:",
        "Aliases:",
        "start, status",
        "Project: https://github.com/GabrielPabloG/aiosdeck",
    )
    for text in expected:
        assert text in output
