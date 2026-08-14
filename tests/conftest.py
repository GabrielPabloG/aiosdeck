import pytest

from aios.agents.executor import AgentExecutor


@pytest.fixture
def agent_executor():
    """Provide an executor whose worker lifecycle is explicit in each test."""
    executor = AgentExecutor()
    yield executor
    executor.shutdown()
