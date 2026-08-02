from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.runtime import RuntimeEngine
from aios.security import SecurityEngine


def test_kernel_start_stop(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.register(RuntimeEngine())
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(project_path=tmp_path))

    kernel.start()
    status = kernel.status()

    assert status["project"] == str(tmp_path)
    assert status["engines"]["config"] == "ready"
    assert status["engines"]["context"] == "ready"
    assert status["engines"]["runtime"] in ("ready", "degraded")
    assert status["engines"]["events"] == "ready"
    assert status["engines"]["security"] == "ready"
    assert len(status["errors"]) <= 1  # runtime may be degraded without opencode

    kernel.shutdown()


def test_kernel_status_all_engines(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.start()

    status = kernel.status()
    assert "config" in status["engines"]
    assert status["engines"]["config"] == "ready"


def test_kernel_get_context(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.start()

    context = kernel.get_context()
    assert context is not None
    assert context.project.language == "python"


def test_kernel_no_engines():
    kernel = Kernel()
    kernel.start()
    status = kernel.status()
    assert len(status["errors"]) == 0
