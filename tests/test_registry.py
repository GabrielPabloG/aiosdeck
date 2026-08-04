from aios.cli.commands import COMMANDS, Command

REQUIRED_COMMANDS = ["dashboard", "doctor", "plan", "help", "exit", "__complete"]


def test_commands_has_all_required_keys():
    for name in REQUIRED_COMMANDS:
        assert name in COMMANDS, f"COMMANDS missing: {name}"


def test_commands_all_have_execute():
    for name in REQUIRED_COMMANDS:
        cmd = COMMANDS[name]
        assert cmd.execute is not None, f"{name}.execute is None"


def test_commands_all_are_command_instances():
    for name in REQUIRED_COMMANDS:
        cmd = COMMANDS[name]
        assert isinstance(cmd, Command), f"{name} is not a Command instance"


def test_dashboard_has_aliases():
    cmd = COMMANDS["dashboard"]
    assert "start" in cmd.aliases
    assert "status" in cmd.aliases


def test_exit_is_hidden():
    cmd = COMMANDS["exit"]
    assert cmd.hidden is True


def test_complete_is_hidden():
    cmd = COMMANDS["__complete"]
    assert cmd.hidden is True


def test_help_is_not_hidden():
    cmd = COMMANDS["help"]
    assert cmd.hidden is False


def test_dashboard_not_hidden():
    cmd = COMMANDS["dashboard"]
    assert cmd.hidden is False
