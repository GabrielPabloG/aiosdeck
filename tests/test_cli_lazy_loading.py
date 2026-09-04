"""Lazy command loading (Issue #42).

The CLI registry must not import domain modules at module level. Loading
``aios.cli.commands`` (and running ``--help`` / ``--version``) must not pull
in ``aios.core``, ``aios.knowledge``, ``aios.backlog``, ``aios.skills``, etc.
"""

import importlib
import subprocess
import sys

import pytest

DOMAIN_PREFIXES = (
    "aios.core",
    "aios.knowledge",
    "aios.backlog",
    "aios.skills",
    "aios.quality",
    "aios.routing",
    "aios.security",
    "aios.learning",
    "aios.telemetry",
    "aios.ui",
    "aios.integrations",
)


def _collect_handlers(command) -> list[str]:
    handlers = []
    if command.handler is not None:
        handlers.append(command.handler)
    for sub in command.subcommands.values():
        handlers.extend(_collect_handlers(sub))
    return handlers


def test_cli_help_does_not_import_domain_modules():
    probe = (
        "import sys\n"
        "from aios.cli.main import main\n"
        "try:\n"
        "    import aios.cli.commands\n"
        "    sys.argv = ['aios', '--help']\n"
        "    main()\n"
        "except SystemExit:\n"
        "    pass\n"
        "bad = [m for m in sys.modules if m.split('.')[0] == 'aios' and "
        "m.startswith(('aios.core', 'aios.knowledge', 'aios.backlog', "
        "'aios.skills', 'aios.quality', 'aios.routing', 'aios.security', "
        "'aios.learning', 'aios.telemetry', 'aios.ui', 'aios.integrations'))]\n"
        "print('IMPORTED_DOMAINS=' + repr(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    imported = [
        line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("IMPORTED_DOMAINS=")
    ]
    assert imported, "probe did not report imported domains"
    assert eval(imported[0]) == [], f"domain modules imported on --help: {imported[0]}"


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_cli_help_and_version_do_not_import_domain_modules(flag):
    probe = (
        "import sys\n"
        "from aios.cli.main import main\n"
        "try:\n"
        "    import aios.cli.commands\n"
        f"    sys.argv = ['aios', {flag!r}]\n"
        "    main()\n"
        "except SystemExit:\n"
        "    pass\n"
        "bad = [m for m in sys.modules if m.startswith(" + repr(DOMAIN_PREFIXES) + ")]\n"
        "print('IMPORTED_DOMAINS=' + repr(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    imported = [line for line in result.stdout.splitlines() if line.startswith("IMPORTED_DOMAINS=")]
    assert eval(imported[0].split("=", 1)[1]) == []


def test_cli_all_commands_still_dispatchable():
    from aios.cli.commands import COMMANDS

    handlers: list[str] = []
    for cmd in COMMANDS.values():
        handlers.extend(_collect_handlers(cmd))

    assert handlers, "no handlers registered — registry is empty"

    for handler_path in handlers:
        module_path, sep, attr = handler_path.partition(":")
        assert sep == ":", f"invalid handler path (missing ':') — {handler_path!r}"
        module = importlib.import_module(module_path)
        handler = getattr(module, attr)
        assert callable(handler), f"handler not callable — {handler_path!r}"
