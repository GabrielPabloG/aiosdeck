"""Smoke test — full flow: kernel → context → agent → runtime → result."""

from unittest.mock import patch

from aios.agents import Task
from aios.agents.developer import DeveloperAgent
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.runtime import RuntimeEngine
from aios.security import SecurityEngine


def test_full_flow(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    kwargs = {"project_path": tmp_path}
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(**kwargs))
    kernel.register(ContextEngine(**kwargs))
    runtime = RuntimeEngine()
    kernel.register(runtime)
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(**kwargs))
    kernel.register(DeveloperAgent(runtime))

    kernel.start()
    status = kernel.status()
    assert len(status["errors"]) <= 1  # runtime may be degraded

    context = kernel.get_context()
    assert context is not None
    assert context.project.language == "python"

    agent = kernel.get_engine("developer")
    assert agent is not None

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Implementation complete.\n"

        result = agent.execute(Task(description="Say hello"), context)
        assert result.success is True
        assert "Implementation complete" in result.output

    kernel.shutdown()
