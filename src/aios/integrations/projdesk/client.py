"""ProjDeskClient — wraps the `pd` CLI behind a domain interface."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aios.integrations.projdesk.exceptions import (
    ProjDeskError,
    ProjectAmbiguous,
    ProjectNotFound,
)

_DEFAULT_TIMEOUT = 5


class ProjDeskClient:
    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def resolve(self, name: str) -> Path:
        try:
            result = subprocess.run(
                ["pd", "resolve", name],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProjDeskError(f"ProjDesk did not respond within {self.timeout}s") from exc
        except FileNotFoundError as exc:
            raise ProjDeskError("ProjDesk (pd) is not installed or not in PATH") from exc

        match result.returncode:
            case 0:
                resolved = Path(result.stdout.strip())
                if resolved.is_dir():
                    return resolved
                raise ProjDeskError(f"Resolved path is not a directory: {resolved}")
            case 1:
                raise ProjectNotFound(name)
            case 2:
                raise ProjectAmbiguous(name)
            case _:
                raise ProjDeskError(result.stderr.strip())
