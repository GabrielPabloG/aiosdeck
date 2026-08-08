"""Tests for mapping effective permissions to the opencode tool policy.

The mapper translates ``EffectivePermissions`` into the ``OPENCODE_PERMISSION``
JSON. The mapping is least-privilege and the bash command policy carries an
explicit deny set (push/tag/rm/curl/wget) that survives ``--auto`` thanks to
opencode's last-match-wins rule: the allowlist always follows the deny rules.
``permissions=None`` returns the legacy coarse-capability output untouched.
"""

import json
from unittest.mock import MagicMock, patch

from aios.agents.contracts import AgentTask
from aios.agents.developer import DeveloperAgent
from aios.context.packet import ContextPacket
from aios.runtime.opencode import OpenCodeAdapter
from aios.security import EffectivePermissions
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
    WORKFLOW_INTENT,
)


def _perms(allowed: frozenset[str]) -> EffectivePermissions:
    return EffectivePermissions(allowed=allowed)


def test_reviewer_maps_to_least_privilege():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({FILESYSTEM_READ_ACTION}))
    perms = json.loads(adapter._build_permissions(effective))
    assert perms["question"] == "deny"
    assert perms["read"] == "allow"
    assert perms["glob"] == "allow"
    assert perms["grep"] == "allow"
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"
    assert perms["webfetch"] == "deny"
    assert perms["websearch"] == "deny"


def test_developer_bash_policy_denies_destructive_commands():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({FILESYSTEM_READ_ACTION, FILESYSTEM_WRITE_ACTION, SHELL_EXECUTE}))
    perms = json.loads(adapter._build_permissions(effective))
    assert perms["edit"] == "allow"
    bash = perms["bash"]
    assert bash["*"] == "deny"
    for command in ("git push *", "git tag *", "rm -rf *", "curl *", "wget *"):
        assert bash[command] == "deny"
    for command in ("git branch *", "git commit *", "grep *", "ruff *", "python *", "pytest *"):
        assert bash[command] == "allow"


def test_bash_allowlist_follows_deny_rules_for_last_match_wins():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({SHELL_EXECUTE}))
    bash = json.loads(adapter._build_permissions(effective))["bash"]
    keys = list(bash)
    assert keys[0] == "*"
    assert keys.index("git push *") < keys.index("git commit *")
    assert keys.index("rm -rf *") < keys.index("python *")


def test_without_shell_execute_bash_is_flat_deny():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({FILESYSTEM_READ_ACTION}))
    perms = json.loads(adapter._build_permissions(effective))
    assert perms["bash"] == "deny"
    assert perms["edit"] == "deny"


def test_network_access_allows_webfetch_and_websearch():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({NETWORK_ACCESS}))
    perms = json.loads(adapter._build_permissions(effective))
    assert perms["webfetch"] == "allow"
    assert perms["websearch"] == "allow"
    assert perms["read"] == "deny"
    assert perms["edit"] == "deny"


def test_permissions_none_returns_legacy_output():
    adapter = OpenCodeAdapter()
    assert adapter._build_permissions(["filesystem_read"]) == json.dumps(
        {"question": "deny", "edit": "deny", "bash": "deny"}
    )
    assert adapter._build_permissions(["filesystem_read", "shell"]) == json.dumps(
        {"question": "deny"}
    )


def test_execute_injects_bash_policy_into_permission_env():
    adapter = OpenCodeAdapter()
    effective = _perms(frozenset({SHELL_EXECUTE}))

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "done"

        adapter.execute("test", skills=[], capabilities=["shell"], permissions=effective)

        env = mock_run.call_args.kwargs["env"]
        perms = json.loads(env["OPENCODE_PERMISSION"])
        assert perms["bash"]["git push *"] == "deny"
        assert perms["bash"]["*"] == "deny"


def test_developer_passes_effective_permissions_to_runtime():
    runtime = MagicMock()
    runtime.execute.return_value = "ok"
    agent = DeveloperAgent(runtime)
    context = ContextPacket()
    context.intent = WORKFLOW_INTENT

    agent.execute(AgentTask(description="implement feature"), context)

    kwargs = runtime.execute.call_args.kwargs
    assert kwargs["permissions"] is not None
    assert SHELL_EXECUTE in kwargs["permissions"]
    assert FILESYSTEM_READ_ACTION in kwargs["permissions"]


def test_developer_without_intent_passes_none_permissions():
    runtime = MagicMock()
    runtime.execute.return_value = "ok"
    agent = DeveloperAgent(runtime)

    agent.execute(AgentTask(description="implement feature"), ContextPacket())

    kwargs = runtime.execute.call_args.kwargs
    assert kwargs.get("permissions") is None
