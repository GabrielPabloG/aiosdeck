"""Runtime adapter selection in the kernel factory — the replaceable runtime.

``create_kernel`` chooses the runtime adapter from ``runtime.adapter`` config
(env ``AIOS_RUNTIME_ADAPTER``): ``ollama`` selects the sandboxed
``OllamaAdapter``; anything else keeps the default ``OpenCodeAdapter``.
"""

import aios.runtime.opencode as opencode_module
from aios.core.factory import create_kernel
from aios.runtime.ollama import OllamaAdapter
from aios.runtime.opencode import OpenCodeAdapter


def test_factory_defaults_to_opencode_adapter(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    monkeypatch.delenv("AIOS_RUNTIME_ADAPTER", raising=False)
    kernel = create_kernel(tmp_path)
    try:
        runtime = kernel.get_engine("runtime")
        assert isinstance(runtime.adapter, OpenCodeAdapter)
    finally:
        kernel.shutdown()


def test_factory_selects_ollama_adapter_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    monkeypatch.setenv("AIOS_RUNTIME_ADAPTER", "ollama")
    kernel = create_kernel(tmp_path)
    try:
        runtime = kernel.get_engine("runtime")
        assert isinstance(runtime.adapter, OllamaAdapter)
    finally:
        kernel.shutdown()


def test_factory_adapter_dispatch_is_config_driven(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOS_MEMORY_PATH", raising=False)
    monkeypatch.setenv("AIOS_RUNTIME_ADAPTER", "ollama")
    calls = []
    real_opencode = opencode_module.OpenCodeAdapter

    def spy(*args, **kwargs):
        calls.append("opencode")
        return real_opencode(*args, **kwargs)

    monkeypatch.setattr(opencode_module, "OpenCodeAdapter", spy)
    kernel = create_kernel(tmp_path)
    try:
        assert isinstance(kernel.get_engine("runtime").adapter, OllamaAdapter)
        assert calls == []
    finally:
        kernel.shutdown()
