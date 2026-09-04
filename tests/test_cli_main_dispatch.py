"""In-process coverage for the CLI entry point (main.py).

The subprocess smoke tests (test_cli.py) are invisible to coverage-guided
mutation testing: main.py's function bodies had zero in-process coverage, so
every mutant scoped there reported "no tests" and failed the Gate C hard-fail.
These tests exercise ``main``, ``_dispatch``, ``_find_command``,
``_resolve_project``, ``_kernel_factory`` and ``_handle_signal`` in-process so
the dispatch contract is actually constrained.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import aios.cli.main  # noqa: F401  (aios.cli rebinds `main` to the function; use sys.modules)
from aios.cli.main import (
    COMMANDS,
    VERSION_TEXT,
    _dispatch,
    _find_command,
    _handle_signal,
    _kernel_factory,
    _resolve_project,
)

main_mod = sys.modules["aios.cli.main"]


def _stub_cmd(handler=None, aliases=None, subcommands=None, name="stub", description="d"):
    return SimpleNamespace(
        name=name,
        description=description,
        aliases=aliases or [],
        subcommands=subcommands or {},
        handler=handler,
        execute=MagicMock(),
    )


# ---------------------------------------------------------------------------
# _handle_signal
# ---------------------------------------------------------------------------


def test_handle_signal_shuts_down_active_kernel(monkeypatch, capsys):
    kernel = MagicMock()
    monkeypatch.setattr(main_mod, "_active_kernel", kernel)

    with pytest.raises(SystemExit) as exc:
        _handle_signal(signal.SIGINT, None)

    assert exc.value.code == 0
    kernel.shutdown.assert_called_once()
    assert capsys.readouterr().err == "\nShutting down...\n"


def test_handle_signal_without_active_kernel_exits_cleanly(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_kernel", None)

    with pytest.raises(SystemExit) as exc:
        _handle_signal(signal.SIGTERM, None)

    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


@pytest.fixture()
def _no_signals(monkeypatch):
    """Keep main() from replacing the process signal handlers during tests."""
    recorded = []
    monkeypatch.setattr(
        main_mod.signal, "signal", lambda sig, handler: recorded.append((sig, handler))
    )
    return recorded


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_main_help_exits_zero_without_dispatch(monkeypatch, capsys, _no_signals, flag):
    spy = MagicMock()
    monkeypatch.setattr(main_mod, "_dispatch", spy)
    monkeypatch.setattr(sys, "argv", ["aios", flag])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 0
    assert "Usage:" in capsys.readouterr().out
    spy.assert_not_called()


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_main_version_prints_and_exits(monkeypatch, capsys, _no_signals, flag):
    spy = MagicMock()
    monkeypatch.setattr(main_mod, "_dispatch", spy)
    monkeypatch.setattr(sys, "argv", ["aios", flag])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == VERSION_TEXT
    spy.assert_not_called()


def test_main_registers_signal_handlers(monkeypatch, _no_signals):
    monkeypatch.setattr(sys, "argv", ["aios", "--version"])
    with pytest.raises(SystemExit):
        main_mod.main()

    handlers = dict(_no_signals)
    assert handlers[signal.SIGINT] is _handle_signal
    assert handlers[signal.SIGTERM] is _handle_signal


def test_main_unknown_command_errors(monkeypatch, capsys, _no_signals):
    monkeypatch.setattr(sys, "argv", ["aios", "frobnicate"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Unknown command: frobnicate" in err
    assert "aios help" in err


def test_main_bare_invokes_dashboard_with_no_args(monkeypatch, _no_signals):
    spy = MagicMock()
    monkeypatch.setattr(main_mod, "_dispatch", spy)
    monkeypatch.setattr(sys, "argv", ["aios"])

    main_mod.main()

    cmd, raw_args, project_path = spy.call_args.args
    assert cmd is COMMANDS["dashboard"]
    assert raw_args == []
    assert project_path == Path.cwd()


def test_main_routes_named_command_with_args(monkeypatch, _no_signals):
    spy = MagicMock()
    monkeypatch.setattr(main_mod, "_dispatch", spy)
    monkeypatch.setattr(sys, "argv", ["aios", "doctor", "--json"])

    main_mod.main()

    cmd, raw_args, project_path = spy.call_args.args
    assert cmd is COMMANDS["doctor"]
    assert raw_args == ["--json"]
    assert project_path == Path.cwd()


def test_main_routes_alias_to_research(monkeypatch, _no_signals):
    spy = MagicMock()
    monkeypatch.setattr(main_mod, "_dispatch", spy)
    monkeypatch.setattr(sys, "argv", ["aios", "r", "why"])

    main_mod.main()

    cmd, raw_args, project_path = spy.call_args.args
    assert cmd is COMMANDS["research"]
    assert raw_args == ["why"]
    assert project_path == Path.cwd()


def test_main_filters_flags_from_positional_project_args(monkeypatch, _no_signals):
    resolve_spy = MagicMock(return_value=Path("/resolved"))
    dispatch_spy = MagicMock()
    monkeypatch.setattr(main_mod, "_resolve_project", resolve_spy)
    monkeypatch.setattr(main_mod, "_dispatch", dispatch_spy)
    monkeypatch.setattr(sys, "argv", ["aios", "plan", "proj-x", "--json"])

    main_mod.main()

    resolve_spy.assert_called_once_with(["proj-x"])
    assert dispatch_spy.call_args.args == (
        COMMANDS["plan"],
        ["proj-x", "--json"],
        Path("/resolved"),
    )


@pytest.mark.parametrize("bare", [True, False])
def test_main_surfaces_projdesk_errors(monkeypatch, capsys, _no_signals, bare):
    from aios.integrations.projdesk.exceptions import ProjDeskError

    monkeypatch.setattr(main_mod, "_resolve_project", MagicMock(side_effect=ProjDeskError("boom")))
    monkeypatch.setattr(sys, "argv", ["aios"] if bare else ["aios", "plan", "x"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 1
    assert "boom" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _find_command
# ---------------------------------------------------------------------------


def test_find_command_matches_exact_name():
    assert _find_command("doctor") is COMMANDS["doctor"]


def test_find_command_matches_alias():
    assert _find_command("mem") is COMMANDS["memory"]


def test_find_command_returns_none_for_unknown():
    assert _find_command("totally-not-real") is None


# ---------------------------------------------------------------------------
# _resolve_project
# ---------------------------------------------------------------------------


def test_resolve_project_no_args_uses_cwd():
    assert _resolve_project([]) == Path.cwd()


def test_resolve_project_existing_dir_resolves(tmp_path):
    assert _resolve_project([str(tmp_path)]) == tmp_path.resolve()


def test_resolve_project_uses_projdesk_for_non_dir(monkeypatch, tmp_path):
    target = tmp_path / "registered-project"
    client = MagicMock()
    client.resolve.return_value = target
    monkeypatch.setattr("aios.integrations.projdesk.ProjDeskClient", MagicMock(return_value=client))

    assert _resolve_project(["registered-project"]) == target
    client.resolve.assert_called_once_with("registered-project")


def test_resolve_project_falls_back_to_cwd_on_projdesk_error(monkeypatch):
    from aios.integrations.projdesk.exceptions import ProjDeskError

    client = MagicMock()
    client.resolve.side_effect = ProjDeskError("nope")
    monkeypatch.setattr("aios.integrations.projdesk.ProjDeskClient", MagicMock(return_value=client))

    assert _resolve_project(["ghost-project"]) == Path.cwd()


# ---------------------------------------------------------------------------
# _dispatch
# ---------------------------------------------------------------------------


def test_dispatch_no_args_with_handler_executes():
    cmd = _stub_cmd(handler="some.module:func")

    _dispatch(cmd, [], Path("/p"))

    cmd.execute.assert_called_once_with([], Path("/p"), main_mod._kernel_factory)


def test_dispatch_no_args_without_handler_prints_help(capsys):
    cmd = _stub_cmd(name="quality", description="Query quality gate telemetry")

    _dispatch(cmd, [], Path("/p"))

    out = capsys.readouterr().out
    assert "quality — Query quality gate telemetry" in out
    cmd.execute.assert_not_called()


def test_dispatch_routes_subcommand_by_name():
    sub = _stub_cmd(name="index", handler="a.knowledge.cli:cmd_knowledge_index")
    parent = _stub_cmd(subcommands={"index": sub})

    _dispatch(parent, ["index", "extra"], Path("/p"))

    sub.execute.assert_called_once_with(["extra"], Path("/p"), main_mod._kernel_factory)
    parent.execute.assert_not_called()


def test_dispatch_routes_subcommand_by_alias():
    sub = _stub_cmd(name="ls", aliases=["l"], handler="pkg:cmd_ls")
    parent = _stub_cmd(subcommands={"list": sub})

    _dispatch(parent, ["l", "arg"], Path("/p"))

    sub.execute.assert_called_once_with(["arg"], Path("/p"), main_mod._kernel_factory)


def test_dispatch_nested_subcommand_recurses():
    leaf = _stub_cmd(name="stats", handler="pkg:cmd_stats")
    mid = _stub_cmd(name="quality", subcommands={"stats": leaf})
    top = _stub_cmd(name="root", subcommands={"quality": mid})

    _dispatch(top, ["quality", "stats", "--json"], Path("/p"))

    leaf.execute.assert_called_once_with(["--json"], Path("/p"), main_mod._kernel_factory)


def test_dispatch_leaf_sub_without_handler_falls_back_to_parent():
    sub = _stub_cmd(name="explain")
    parent = _stub_cmd(name="route", handler="pkg:cmd_route", subcommands={"explain": sub})

    _dispatch(parent, ["explain", "task"], Path("/p"))

    parent.execute.assert_called_once_with(
        ["explain", "task"], Path("/p"), main_mod._kernel_factory
    )
    sub.execute.assert_not_called()


def test_dispatch_leaf_sub_without_parent_handler_prints_sub_help(capsys):
    sub = _stub_cmd(name="approve", description="Approve a learning candidate")
    parent = _stub_cmd(name="learning", subcommands={"approve": sub})

    _dispatch(parent, ["approve"], Path("/p"))

    assert "approve — Approve a learning candidate" in capsys.readouterr().out
    sub.execute.assert_not_called()
    parent.execute.assert_not_called()


def test_dispatch_unknown_subcommand_with_handler_executes_parent():
    sub = _stub_cmd(name="index")
    parent = _stub_cmd(name="route", handler="pkg:cmd_route", subcommands={"index": sub})

    _dispatch(parent, ["weird", "x"], Path("/p"))

    parent.execute.assert_called_once_with(["weird", "x"], Path("/p"), main_mod._kernel_factory)


def test_dispatch_unknown_subcommand_without_handler_errors(capsys):
    parent = _stub_cmd(name="quality", subcommands={"stats": _stub_cmd(name="stats")})

    with pytest.raises(SystemExit) as exc:
        _dispatch(parent, ["bogus"], Path("/p"))

    assert exc.value.code == 1
    assert "Unknown subcommand: bogus" in capsys.readouterr().err
    parent.execute.assert_not_called()


def test_dispatch_args_without_subcommands_execute_handler():
    cmd = _stub_cmd(name="plan", handler="pkg:cmd_plan")

    _dispatch(cmd, ["build", "an", "api"], Path("/p"))

    cmd.execute.assert_called_once_with(
        ["build", "an", "api"], Path("/p"), main_mod._kernel_factory
    )


# ---------------------------------------------------------------------------
# _kernel_factory
# ---------------------------------------------------------------------------


def test_kernel_factory_creates_and_tracks_kernel(monkeypatch, tmp_path):
    import aios.core.factory as factory_mod

    kernel = MagicMock()
    create = MagicMock(return_value=kernel)
    monkeypatch.setattr(factory_mod, "create_kernel", create)
    monkeypatch.setattr(main_mod, "_active_kernel", None)

    result = _kernel_factory(tmp_path)

    assert result is kernel
    create.assert_called_once_with(tmp_path)
    assert main_mod._active_kernel is kernel
