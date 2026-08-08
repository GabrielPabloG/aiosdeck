"""OpenCode runtime adapter — always invoked through ai-jail."""

import json
import logging
import os
import shutil
import subprocess

from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
)
from aios.security.contracts import EffectivePermissions

logger = logging.getLogger("aios.runtime.opencode")

# Bash command policy. opencode's last-match-wins rule means the deny rules must
# precede the run allowlist so an explicit deny always survives ``--auto``.
_BASH_RULES: dict[str, str] = {
    "*": "deny",
    "git push *": "deny",
    "git tag *": "deny",
    "rm -rf *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git branch *": "allow",
    "git commit *": "allow",
    "grep *": "allow",
    "ruff *": "allow",
    "python *": "allow",
    "pytest *": "allow",
}


class OpenCodeAdapter:
    name = "opencode"
    version = "1.0"

    def __init__(self) -> None:
        self._opencode_installed = False
        self._ai_jail_installed = False
        self._resolved_command = "opencode"
        self._permission_cache: dict[tuple[str, ...], str] = {}

    def initialize(self) -> None:
        self._opencode_installed = shutil.which("opencode") is not None
        self._ai_jail_installed = shutil.which("ai-jail") is not None
        self._resolve_command()

    def health_check(self) -> bool:
        return self._opencode_installed

    def shutdown(self) -> None:
        pass

    @property
    def command(self) -> str:
        return self._resolved_command

    @property
    def has_sandbox(self) -> bool:
        return self._ai_jail_installed

    def _resolve_command(self) -> None:
        if not self._opencode_installed:
            self._resolved_command = "opencode (not found)"
            return

        if self._ai_jail_installed:
            self._resolved_command = "ai-jail opencode"
        else:
            self._resolved_command = "opencode"
            logger.warning("ai-jail not found. Running OpenCode without sandbox.")

    def execute(  # noqa: PLR0913
        self,
        prompt: str,
        skills: list[str],
        capabilities: list[str] | None = None,
        permissions: EffectivePermissions | None = None,
        *,
        model: str = "",
        variant: str = "",
    ) -> str:
        args = self._resolved_command.split()
        args.extend(["run", prompt])

        if model:
            args.extend(["-m", model])
        if variant:
            args.extend(["--variant", variant])

        args.append("--auto")

        if not self._opencode_installed:
            raise RuntimeError(f"Runtime not available: {self._resolved_command}")

        env = os.environ.copy()
        if permissions is not None:
            permissions_json = self._build_permissions(permissions)
        else:
            permissions_json = self._build_permissions(capabilities or [])
        env["OPENCODE_PERMISSION"] = permissions_json

        try:
            kwargs: dict = {
                "text": True,
                "timeout": 600,
                "env": env,
                "capture_output": True,
            }

            result = subprocess.run(args, check=False, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Runtime execution timed out after 600s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"Runtime command not found: {self._resolved_command}") from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "unknown error"
            raise RuntimeError(f"Runtime exited with code {result.returncode}: {stderr}")

        return result.stdout.strip() if result.stdout else ""

    def _build_permissions(
        self,
        effective: EffectivePermissions | list[str] | None = None,
        capabilities: list[str] | None = None,
    ) -> str:
        """Build the ``OPENCODE_PERMISSION`` JSON.

        A resolved ``EffectivePermissions`` maps each granular action to the
        least-privilege tool policy. A list (or nothing) is the legacy coarse
        capability path, byte-identical to previous output.
        """
        if isinstance(effective, EffectivePermissions):
            return self._build_effective_permissions(effective)
        if isinstance(effective, frozenset):
            return self._build_effective_permissions(EffectivePermissions(allowed=effective))
        return self._build_legacy_permissions(
            effective if isinstance(effective, list) else capabilities or []
        )

    def _build_legacy_permissions(self, capabilities: list[str]) -> str:
        key = ("legacy",) + tuple(sorted(capabilities))
        if key in self._permission_cache:
            return self._permission_cache[key]

        permissions: dict[str, str] = {
            "question": "deny",
        }

        if "filesystem_write" not in capabilities and "shell" not in capabilities:
            permissions["edit"] = "deny"
            permissions["bash"] = "deny"

        json_str = json.dumps(permissions)
        self._permission_cache[key] = json_str
        return json_str

    def _build_effective_permissions(self, effective: EffectivePermissions) -> str:
        key = ("effective",) + tuple(sorted(effective.allowed))
        if key in self._permission_cache:
            return self._permission_cache[key]

        allowed = effective.allowed
        read = FILESYSTEM_READ_ACTION in allowed
        write = FILESYSTEM_WRITE_ACTION in allowed
        shell = SHELL_EXECUTE in allowed
        network = NETWORK_ACCESS in allowed

        permissions: dict[str, str | dict[str, str]] = {
            "question": "deny",
            "read": "allow" if read else "deny",
            "glob": "allow" if read else "deny",
            "grep": "allow" if read else "deny",
            "edit": "allow" if write else "deny",
            "webfetch": "allow" if network else "deny",
            "websearch": "allow" if network else "deny",
        }
        permissions["bash"] = _BASH_RULES if shell else "deny"

        json_str = json.dumps(permissions)
        self._permission_cache[key] = json_str
        return json_str
