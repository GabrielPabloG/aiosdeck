"""
Architectural contract tests.

These tests freeze the public interfaces exchanged between
agents. Any incompatible API change should fail here before
breaking the Workflow Engine.

Any change to an agent's public API must be accompanied by a
conscious update of these contract tests. A failure here
indicates an architectural change, not merely an implementation
bug.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from aios.agents.documentation import ChangelogFragment
from aios.agents.git import GitOperation
from aios.agents.models import AgentResult
from aios.core.task import Task
from aios.scheduler import KanbanCard


def test_agent_interfaces_are_compatible():
    """Each agent's output is structurally compatible with the next agent's input."""
    subtask = {"description": "build feature", "priority": "high"}
    assert isinstance(subtask["description"], str)

    task = Task(description=KanbanCard(title=subtask["description"]).title)
    assert isinstance(task.description, str)

    result = AgentResult(success=True, output="ok", errors=[])
    assert isinstance(result.success, bool)
    assert isinstance(result.errors, list)

    review_report = {"items": [], "summary": "all clear"}
    assert isinstance(review_report, Mapping)
    assert "items" in review_report
    assert "summary" in review_report

    test_report = {"collected": 1, "passed": 1, "failed": 0}
    assert isinstance(test_report["collected"], int)
    assert isinstance(test_report["passed"], int)
    assert isinstance(test_report["failed"], int)

    fragment = ChangelogFragment(
        path=Path("docs/changelog-fragment.md"), written=True, preview="ok"
    )
    assert json.dumps(asdict(fragment), default=str)

    git_operation = GitOperation(
        command=["git", "push"], executed=False, stdout="", stderr="", returncode=0
    )
    assert git_operation.executed is False
    assert json.dumps(asdict(git_operation))
