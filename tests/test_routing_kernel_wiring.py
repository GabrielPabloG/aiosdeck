"""Integration tests for routing wired into the production kernel factory.

``aios.cli.main._create_kernel`` must build the runtime router from the
routing config before ``kernel.start()`` ever runs, so that real ``aios plan
--run`` invocations select a model instead of silently running with the
default one.
"""

from pathlib import Path

import pytest

from aios.cli.main import _create_kernel
from aios.routing.models import RouteInput


def _write_user_config(tmp_path: Path, yaml_text: str) -> None:
    config_dir = tmp_path / ".config" / "aiosdeck"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text(yaml_text)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("AIOS_ROUTING_ENABLED", "AIOS_ROUTING_COST_CAP"):
        monkeypatch.delenv(key, raising=False)


class TestCreateKernelRouterWiring:
    def test_router_wired_when_routing_enabled(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        _write_user_config(
            tmp_path,
            "routing:\n"
            "  enabled: true\n"
            "  rules:\n"
            "    - agent: developer\n"
            "      provider: openrouter\n"
            "      model: openrouter/deepseek/deepseek-v4-flash\n",
        )

        kernel = _create_kernel(tmp_path)

        runtime = kernel.get_engine("runtime")
        assert runtime is not None
        assert runtime.router is not None

        decision = runtime.router.route(RouteInput(agent="developer"))
        assert decision.model == "openrouter/deepseek/deepseek-v4-flash"
        assert decision.provider == "openrouter"

    def test_router_disabled_when_routing_disabled(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        _write_user_config(
            tmp_path,
            "routing:\n  enabled: false\n",
        )

        kernel = _create_kernel(tmp_path)

        runtime = kernel.get_engine("runtime")
        assert runtime is not None
        assert runtime.router is None

    def test_router_installed_with_defaults_without_user_config(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        kernel = _create_kernel(tmp_path)

        runtime = kernel.get_engine("runtime")
        assert runtime is not None
        assert runtime.router is not None
        decision = runtime.router.route(RouteInput(agent="planner"))
        assert decision.model == "ollama/llama3"
