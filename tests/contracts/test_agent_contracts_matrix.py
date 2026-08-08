"""Per-agent contract tests driven by the Agent Core Compliance Matrix.

For every agent the matrix declares capabilities, timeout, retry policy, and
error behavior. These tests verify each agent's runtime metadata, its
contract method, and its behavior at the execution boundary.
"""

from unittest.mock import MagicMock

import pytest

from aios.agents.contracts import VALIDATION_ERROR, AgentCapabilities, AgentMetadata, AgentTask
from aios.agents.executor import AgentExecutor, make_request
from tests.agent_compliance_matrix import AGENT_COMPLIANCE_MATRIX


def _instantiate(spec):
    cls = spec["agent_class"]
    if cls.__name__ in ("PlannerAgent", "DeveloperAgent"):
        return cls(MagicMock())
    return cls()


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_metadata_matches_matrix(name):
    spec = AGENT_COMPLIANCE_MATRIX[name]
    agent = _instantiate(spec)
    assert isinstance(agent.metadata, AgentMetadata)
    assert agent.metadata.name == name
    assert agent.metadata.timeout == spec["timeout"]
    assert agent.metadata.retry_policy.max_attempts == spec["retry"]["max_attempts"]
    assert set(agent.metadata.retry_policy.retryable_codes) == set(spec["retry"]["retryable_codes"])


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_capabilities_match_matrix(name):
    spec = AGENT_COMPLIANCE_MATRIX[name]
    agent = _instantiate(spec)
    assert isinstance(agent.capabilities, AgentCapabilities)
    assert set(agent.capabilities.permissions) == set(spec["capabilities"])
    privileged = {"shell", "git", "internet", "filesystem_write"}
    assert agent.capabilities.is_read_only == (not set(spec["capabilities"]) & privileged)


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_execute_is_the_public_contract(name):
    spec = AGENT_COMPLIANCE_MATRIX[name]
    agent = _instantiate(spec)
    assert callable(agent.execute)


@pytest.mark.parametrize("name", AGENT_COMPLIANCE_MATRIX)
def test_agent_input_validation_at_boundary(name):
    """An invalid AgentTask yields VALIDATION_ERROR from the executor."""
    agent = _instantiate(AGENT_COMPLIANCE_MATRIX[name])
    outcome = AgentExecutor().execute(make_request(agent, AgentTask(description="")))
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert outcome.error.code == VALIDATION_ERROR
