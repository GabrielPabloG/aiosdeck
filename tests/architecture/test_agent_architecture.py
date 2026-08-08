"""Architecture checks for the Agent Core Hardening (v0.9.2) boundary rules.

These static tests enforce both directions of the execution boundary:

1. Agents are executor-free: no agent module imports or references
   ``AgentExecutor`` (recursion is structurally impossible).
2. WorkflowEngine/CLI/Kernel route exclusively through ``execute()`` / the
   Kernel — they never call the rich domain execution APIs.
3. The runtime is only reached through the runtime adapter, from inside an
   agent's ``execute()`` — never from orchestration code.
4. Only ``AgentExecutor`` may publish ``agent.*`` lifecycle topics, anywhere
   in the project.
5. The legacy ``agent.execution.*`` vocabulary is fully removed.
"""

import re
from pathlib import Path

from aios.events.events import (
    AGENT_EXECUTION_CANCELLED,
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_PROGRESS,
    AGENT_EXECUTION_RETRIED,
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_TIMED_OUT,
    AGENT_LIFECYCLE_CHANGED,
)
from tests.agent_compliance_matrix import AGENT_COMPLIANCE_MATRIX

REPO_ROOT = Path(__file__).resolve().parents[2]

AGENT_LIFECYCLE_TOPICS = {AGENT_LIFECYCLE_CHANGED}
AGENT_EXECUTION_TOPICS = {
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_PROGRESS,
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_TIMED_OUT,
    AGENT_EXECUTION_RETRIED,
    AGENT_EXECUTION_CANCELLED,
}
AGENT_TOPICS = AGENT_LIFECYCLE_TOPICS | AGENT_EXECUTION_TOPICS
AGENT_CONSTANT_NAMES = {
    "AGENT_LIFECYCLE_CHANGED",
    "AGENT_EXECUTION_STARTED",
    "AGENT_EXECUTION_PROGRESS",
    "AGENT_EXECUTION_COMPLETED",
    "AGENT_EXECUTION_FAILED",
    "AGENT_EXECUTION_TIMED_OUT",
    "AGENT_EXECUTION_RETRIED",
    "AGENT_EXECUTION_CANCELLED",
}

ORCHESTRATION_FILES = [
    "src/aios/workflow/engine.py",
    "src/aios/cli/commands.py",
    "src/aios/cli/main.py",
    "src/aios/core/kernel.py",
]

# The rich domain execution APIs are private methods of the agents.
RICH_API_PATTERNS = [
    r"\._review\(",
    r"\._research\(",
    r"\._run\(",
    r"\._generate_changelog_fragment\(",
    r"\._stage\(",
    r"\._commit\(",
    r"\._create_branch\(",
    r"\._create_tag\(",
    r"\._push\(",
]
RICH_API_LEGACY_PATTERNS = [
    r"\.review\(",
    r"\.research\(",
    r"\.generate_changelog_fragment\(",
]

AGENT_MODULES = [
    "src/aios/agents/planner.py",
    "src/aios/agents/developer.py",
    "src/aios/agents/research.py",
    "src/aios/agents/reviewer.py",
    "src/aios/agents/tester.py",
    "src/aios/agents/documentation.py",
    "src/aios/agents/git.py",
]


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        parts = path.parts
        if any(seg in parts for seg in (".venv", ".venv-pypi", "__pycache__", "dist", ".opencode")):
            continue
        yield path


def _publish_first_arg(line: str) -> str:
    idx = line.find("(")
    if idx == -1:
        return ""
    rest = line[idx + 1 :]
    depth = 0
    for j, ch in enumerate(rest):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return rest[:j].strip()
    return rest.strip()


# ---------------------------------------------------------------------------
# 1. Agents are executor-free (no recursion possible)
# ---------------------------------------------------------------------------


def test_agents_never_import_or_reference_agentexecutor():
    violations = []
    for rel in AGENT_MODULES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if re.search(
            r"(from aios\.agents\.executor import|import aios\.agents\.executor|AgentExecutor\()",
            source,
        ):
            violations.append(rel)
    assert violations == []


def test_every_agent_module_is_in_compliance_matrix():
    known = {
        "planner",
        "developer",
        "research",
        "reviewer",
        "tester",
        "documentation",
        "git",
    }
    assert set(AGENT_COMPLIANCE_MATRIX) == known


# ---------------------------------------------------------------------------
# 2. Orchestrators never call the rich domain APIs
# ---------------------------------------------------------------------------


def test_orchestrators_never_call_rich_domain_apis():
    violations = []
    for rel in ORCHESTRATION_FILES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for pattern in RICH_API_PATTERNS + RICH_API_LEGACY_PATTERNS:
            for match in re.finditer(pattern, source):
                violations.append(f"{rel}: {match.group(0)}")
    assert violations == []


# ---------------------------------------------------------------------------
# 3. The runtime is only reached through the adapter, inside agent code
# ---------------------------------------------------------------------------


def test_orchestrators_never_touch_the_runtime_directly():
    violations = []
    for rel in ORCHESTRATION_FILES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for pattern in (
            r"runtime\.execute\(",
            r"OpenCodeAdapter",
            r"RuntimeAdapter",
            r"self\._runtime",
        ):
            for match in re.finditer(pattern, source):
                violations.append(f"{rel}: {match.group(0)}")
    assert violations == []


def test_agents_only_reach_runtime_via_the_adapter_attribute():
    violations = []
    for rel in AGENT_MODULES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if "aios.runtime" in source or "OpenCodeAdapter" in source or "RuntimeAdapter" in source:
            violations.append(rel)
    assert violations == []


# ---------------------------------------------------------------------------
# 4. Only AgentExecutor publishes agent.* lifecycle topics (project-wide)
# ---------------------------------------------------------------------------


def test_only_executor_publishes_agent_lifecycle_topics():
    violations = []
    for path in _iter_python_files(REPO_ROOT):
        if str(path.relative_to(REPO_ROOT)) == "src/aios/agents/executor.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ".publish(" not in line:
                continue
            arg = _publish_first_arg(line)
            clean = arg.strip().strip("\"'")
            if clean in AGENT_TOPICS or any(name in arg for name in AGENT_CONSTANT_NAMES):
                violations.append(f"{path}:{lineno}: {line.strip()}")
    assert violations == []


# ---------------------------------------------------------------------------
# 5. The legacy agent.execution.* vocabulary is gone
# ---------------------------------------------------------------------------


def test_no_legacy_agent_execution_vocabulary():
    """The legacy 'finished' topic is gone; started/failed now belong to the
    execution tier and are the same strings, so only 'finished' is checked."""
    violations = []
    src_root = REPO_ROOT / "src"
    for path in src_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "agent.execution.finished" in source or "AGENT_EXECUTION_FINISHED" in source:
            violations.append(str(path))
    assert violations == []


# ---------------------------------------------------------------------------
# 6. Matrix-driven verdict: every agent passes every category
# ---------------------------------------------------------------------------


def test_compliance_matrix_verdicts():
    """Every agent in the matrix passes capabilities, timeout, retry, events."""
    required_categories = {"capabilities", "timeout", "retry", "events", "error_behavior"}
    for name, spec in AGENT_COMPLIANCE_MATRIX.items():
        missing = required_categories - set(spec)
        assert not missing, f"{name}: missing matrix categories {missing}"
        assert set(spec["capabilities"]), f"{name}: no capabilities declared"
        assert spec["timeout"] is not None, f"{name}: timeout must be set"
        assert spec["retry"]["max_attempts"] >= 1, f"{name}: invalid retry policy"
        assert {"agent.execution.started", "agent.lifecycle.changed"} <= set(spec["events"]), (
            f"{name}: missing required lifecycle/execution events"
        )
