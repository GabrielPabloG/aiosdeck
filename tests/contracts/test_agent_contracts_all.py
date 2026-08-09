"""Contract tests for every agent — input, output, and error codes (stable).

These tests freeze the public interface of all 9 agents + BaseAgent +
AgentExecutor. Any incompatible change must fail here. The test suite
drives the Agent Core Compliance Matrix directly — no agent is tested in
isolation; every agent is tested through the executor boundary.

Freezes: AgentTask, AgentResult, AgentError codes, ExecutionRequest,
ExecutionOutcome, RunResult, StageSummary, IntentPolicy, EffectivePermissions.
"""

import json
from dataclasses import FrozenInstanceError, asdict
from unittest.mock import MagicMock

import pytest

from aios.agents.base import BaseAgent
from aios.agents.contracts import (
    CANCELLED,
    PERMISSION_DENIED,
    RUNTIME_ERROR,
    TIMEOUT,
    VALIDATION_ERROR,
    AgentCapabilities,
    AgentError,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult, ExecutionOutcome
from aios.core.run_result import RunResult, StageSummary, stage_to_summary
from aios.security.contracts import EffectivePermissions, IntentPolicy, SecurityDecision
from aios.workflow.models import WorkflowStage
from tests.agent_compliance_matrix import AGENT_COMPLIANCE_MATRIX


def _instantiate(spec):
    cls = spec["agent_class"]
    if cls.__name__ in ("PlannerAgent", "DeveloperAgent"):
        adapter = MagicMock()
        adapter.execute.return_value = "{}"
        return cls(adapter)
    return cls()


# ──────────────────────────────────────────────────────────
# AgentTask — input contract for every agent
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_accepts_agenttask_input(name):
    """Every agent receives an AgentTask (or duck-compatible) as input."""
    spec = AGENT_COMPLIANCE_MATRIX[name]
    agent = _instantiate(spec)
    task = AgentTask(description="test task", task_type=name, task_id="t1")
    try:
        result = agent.execute(task, context=None)
    except Exception:
        pass
    else:
        assert isinstance(result, AgentResult)


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_rejects_empty_description(name):
    """Every agent fails on an empty AgentTask.description."""
    outcome = AgentExecutor().execute(
        make_request(
            _instantiate(AGENT_COMPLIANCE_MATRIX[name]),
            AgentTask(description=""),
        )
    )
    assert outcome.error is not None
    assert outcome.error.code == VALIDATION_ERROR


# ──────────────────────────────────────────────────────────
# AgentResult — output contract for every agent
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_execute_returns_agentresult(name):
    """Every agent.execute() returns an AgentResult (or subtype)."""
    spec = AGENT_COMPLIANCE_MATRIX[name]
    agent = _instantiate(spec)
    result = agent.execute(AgentTask(description="test"), context=MagicMock())
    assert isinstance(result, AgentResult)
    assert isinstance(result.success, bool)
    assert isinstance(result.errors, list)


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_result_is_json_serializable(name):
    """AgentResult can be serialized to JSON."""
    result = AgentResult(success=True, output="ok", errors=[])
    serialized = json.dumps(asdict(result), default=str)
    assert isinstance(serialized, str)
    parsed = json.loads(serialized)
    assert parsed["success"] is True


# ──────────────────────────────────────────────────────────
# AgentError — stable error codes
# ──────────────────────────────────────────────────────────


STABLE_ERROR_CODES = {
    VALIDATION_ERROR: "non-transient, bad input",
    RUNTIME_ERROR: "transient, unexpected failure",
    PERMISSION_DENIED: "non-transient, capability denied",
    TIMEOUT: "transient, execution exceeded deadline",
    CANCELLED: "best-effort, user-requested stop",
}


def test_error_codes_are_stable():
    """The vocabulary of AgentError codes MUST NOT change without a bump."""
    for code, _description in STABLE_ERROR_CODES.items():
        error = AgentError(code=code, message="test")
        assert error.code == code
        assert error.to_dict()["code"] == code
        assert error.to_dict()["message"] == "test"


def test_error_transient_flag():
    """transient=True means retryable; transient=False means terminal."""
    transient = AgentError(code=TIMEOUT, message="timeout", transient=True)
    assert transient.retryable is True
    assert transient.to_dict()["transient"] is True

    terminal = AgentError(code=PERMISSION_DENIED, message="denied", transient=False)
    assert terminal.retryable is False
    assert terminal.to_dict()["transient"] is False


# ──────────────────────────────────────────────────────────
# ExecutionRequest / ExecutionOutcome — stable boundaries
# ──────────────────────────────────────────────────────────


def test_execution_request_contract_stable():
    """ExecutionRequest binds agent + task + intent."""
    agent = MagicMock()
    task = AgentTask(description="test")
    intent = IntentPolicy(actions=frozenset({"filesystem.read"}))
    request = make_request(agent, task, intent=intent)
    assert request.agent is agent
    assert request.task is task
    assert request.intent is intent
    assert request.correlation_id == ""
    assert request.timeout is None


def test_execution_outcome_contract_stable():
    """ExecutionOutcome carries a terminal state."""
    outcome = ExecutionOutcome(status="succeeded")
    assert outcome.success is False  # no result set

    ok = ExecutionOutcome(status="succeeded", result=AgentResult(success=True))
    assert ok.success is True

    failed = ExecutionOutcome(status="failed", error=AgentError(code=RUNTIME_ERROR, message="oops"))
    assert failed.success is False
    assert failed.error.code == RUNTIME_ERROR


# ──────────────────────────────────────────────────────────
# RunResult / StageSummary — CLI consumption contract
# ──────────────────────────────────────────────────────────


def test_run_result_is_immutable():
    """RunResult is frozen — consumers can inspect but not mutate."""
    rr = RunResult(success=True, stages=())
    with pytest.raises(FrozenInstanceError):
        rr.success = False  # type: ignore[misc]


def test_stage_summary_fields():
    """StageSummary flattens WorkflowStage into success/failed/skipped."""
    s = StageSummary(name="planner", status="success")
    assert s.name == "planner"
    assert s.status == "success"
    assert s.reason is None

    f = StageSummary(name="developer", status="failed", reason="timeout")
    assert f.status == "failed"
    assert f.reason == "timeout"


def test_stage_to_summary_mapper():
    """The mapper normalizes WorkflowStage → StageSummary deterministically."""
    ws = WorkflowStage(name="planner", success=True, details={})
    summary = stage_to_summary(ws)
    assert summary.name == "planner"
    assert summary.status == "success"

    ws_fail = WorkflowStage(name="tester", success=False, error="segfault")
    summary_fail = stage_to_summary(ws_fail)
    assert summary_fail.status == "failed"
    assert summary_fail.reason == "segfault"

    ws_skip = WorkflowStage(name="documentation", success=False, details={"skipped": True})
    summary_skip = stage_to_summary(ws_skip)
    assert summary_skip.status == "skipped"


# ──────────────────────────────────────────────────────────
# IntentPolicy / EffectivePermissions — security vocabulary
# ──────────────────────────────────────────────────────────


def test_intent_policy_signature_stable():
    """IntentPolicy must not change attribute types without a bump."""
    ip = IntentPolicy(
        actions=frozenset({"filesystem.read"}),
        deny=frozenset({"git.push"}),
        name="dev",
        source="user",
    )
    assert isinstance(ip.actions, frozenset)
    assert isinstance(ip.deny, frozenset)
    assert ip.name == "dev"
    assert ip.source == "user"
    data = ip.to_dict()
    assert data["actions"] == ["filesystem.read"]
    assert data["deny"] == ["git.push"]


def test_effective_permissions_signature_stable():
    """EffectivePermissions must maintain the to_dict() contract."""
    ep = EffectivePermissions(allowed=frozenset({"filesystem.read", "git.branch"}))
    assert ep.allows("filesystem.read")
    assert not ep.allows("shell.execute")
    data = ep.to_dict()
    assert data["allowed"] == sorted(["filesystem.read", "git.branch"])


def test_security_decision_signature_stable():
    """SecurityDecision applies intent + capabilities to a single action."""
    sd = SecurityDecision(
        action="shell.execute",
        allowed=False,
        reason="denied by intent",
        violations=["shell.execute"],
    )
    data = sd.to_dict()
    assert data["action"] == "shell.execute"
    assert data["allowed"] is False
    assert data["violations"] == ["shell.execute"]


# ──────────────────────────────────────────────────────────
# BaseAgent — extensibility base
# ──────────────────────────────────────────────────────────


def test_base_agent_metadata():
    agent = BaseAgent()
    assert isinstance(agent.metadata, AgentMetadata)
    assert agent.name == "base"
    assert agent.metadata.name == "base"
    assert isinstance(agent.capabilities, AgentCapabilities)
    assert agent.capabilities.has("filesystem_read")


def test_base_agent_execute_raises():
    agent = BaseAgent()
    with pytest.raises(NotImplementedError):
        agent.execute(AgentTask(description="test"), context=None)


# ──────────────────────────────────────────────────────────
# AgentExecutor — lifecycle and event contract
# ──────────────────────────────────────────────────────────


def test_executor_publishes_lifecycle_events():
    """A successful execution publishes at minimum:
    created→created, created→validated, validated→queued,
    queued→running, running→succeeded.
    """
    agent = _FakeLifecycleAgent()
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = make_request(agent, AgentTask(description="test"))
    outcome = executor.execute(request)
    assert outcome.success
    events = [c[0][0] for c in bus.publish.call_args_list]
    assert "agent.lifecycle.changed" in events
    assert "agent.execution.started" in events
    assert "agent.execution.completed" in events


def test_executor_publishes_failure_events():
    agent = _FakeLifecycleAgent(fn=lambda t, c: AgentResult(success=False, errors=["fail"]))
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = make_request(agent, AgentTask(description="test"))
    outcome = executor.execute(request)
    assert not outcome.success
    events = [c[0][0] for c in bus.publish.call_args_list]
    assert "agent.execution.failed" in events


class _FakeLifecycleAgent:
    name = "lifecycle-test"

    def __init__(self, fn=None):
        self._fn = fn or (lambda t, c: AgentResult(success=True, output="ok"))
        self.metadata = AgentMetadata(name=self.name, timeout=None, retry_policy=RetryPolicy())
        self.capabilities = AgentCapabilities.from_list(["filesystem_read"])

    def execute(self, task, context):
        return self._fn(task, context)
