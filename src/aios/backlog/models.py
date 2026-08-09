"""Backlog data models."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class BacklogTask:
    title: str
    type: str = "feat"
    scope: str = ""
    subject: str = ""
    version: str = ""
    source: str = ""
    index: int = 0


@dataclass
class BacklogRunResult:
    task: BacklogTask
    status: Literal["succeeded", "failed", "skipped"] = "succeeded"
    commit_sha: str = ""
    duration_ms: float = 0.0
    error: str = ""
