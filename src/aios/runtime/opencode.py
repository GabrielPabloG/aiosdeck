"""OpenCode runtime adapter — always invoked through ai-jail."""

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("aios.runtime.opencode")


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

    def execute(self, prompt: str, skills: list[str], capabilities: list[str] | None = None) -> str:
        args = self._resolved_command.split()
        args.extend(["run", prompt, "--auto"])

        if not self._opencode_installed:
            raise RuntimeError(f"Runtime not available: {self._resolved_command}")

        env = os.environ.copy()
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

    def _build_permissions(self, capabilities: list[str]) -> str:
        key = tuple(sorted(capabilities))
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
