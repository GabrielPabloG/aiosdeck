"""Tests for OllamaAdapter — sandboxed local generation through ai-jail.

The adapter is generation-only (no tool surface) and every model call runs
inside ``ai-jail``: a missing sandbox is a hard failure, never a fallback.
All tests mock ``subprocess.run`` so no jail or model is required.
"""

import json
from unittest.mock import patch

import pytest

from aios.runtime.ollama import OllamaAdapter


class _FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _chat_reply(content: str = '{"goal": "x"}') -> str:
    return json.dumps({"message": {"role": "assistant", "content": content}})


def _patch_run(result: _FakeResult, captured: dict):
    def fake_run(args, *, input, text, capture_output, timeout, check):  # noqa: ARG001, PLR0913
        captured["args"] = args
        captured["input"] = json.loads(input)
        return result

    return patch("aios.runtime.ollama.subprocess.run", side_effect=fake_run)


class TestExecuteContract:
    def test_strips_provider_prefix_and_forces_json(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        captured: dict = {}
        with _patch_run(_FakeResult(stdout=_chat_reply()), captured):
            out = adapter.execute("hi", [], [], model="ollama/llama3.2")

        assert out == '{"goal": "x"}'
        assert captured["args"][:3] == ["ai-jail", "--", "python3"]
        body = captured["input"]["body"]
        assert captured["input"]["url"].endswith("/api/chat")
        assert body["model"] == "llama3.2"
        assert body["format"] == "json"
        assert body["options"]["num_ctx"] > 0
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert body["stream"] is False

    def test_default_model_when_no_override(self):
        adapter = OllamaAdapter(model="llama3")
        adapter._ai_jail_installed = True
        captured: dict = {}
        with _patch_run(_FakeResult(stdout=_chat_reply()), captured):
            adapter.execute("hi", [], [])
        assert captured["input"]["body"]["model"] == "llama3"

    def test_model_without_prefix_kept_as_is(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        captured: dict = {}
        with _patch_run(_FakeResult(stdout=_chat_reply()), captured):
            adapter.execute("hi", [], [], model="llama3.2")
        assert captured["input"]["body"]["model"] == "llama3.2"

    def test_ignores_skills_capabilities_permissions(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        captured: dict = {}
        with _patch_run(_FakeResult(stdout=_chat_reply()), captured):
            adapter.execute("hi", ["skill-a"], ["shell"], permissions=object())
        body = captured["input"]["body"]
        assert body["messages"][0]["content"] == "hi"

    def test_raises_when_sandbox_missing(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = False
        with (
            patch("aios.runtime.ollama.subprocess.run") as mock_run,
            pytest.raises(RuntimeError, match="ai-jail"),
        ):
            adapter.execute("hi", [], [])
        mock_run.assert_not_called()

    def test_raises_on_nonzero_exit(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        with (
            _patch_run(_FakeResult(returncode=1, stderr="boom"), {}),
            pytest.raises(RuntimeError, match="boom"),
        ):
            adapter.execute("hi", [], [])

    def test_raises_when_content_missing(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        with (
            _patch_run(_FakeResult(stdout=json.dumps({"done": True})), {}),
            pytest.raises(RuntimeError, match="message.content"),
        ):
            adapter.execute("hi", [], [])


class TestHealthCheck:
    def test_healthy_when_tags_available(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        captured: dict = {}
        with _patch_run(
            _FakeResult(stdout=json.dumps({"models": [{"name": "llama3.2:latest"}]})), captured
        ):
            assert adapter.health_check() is True
        assert captured["input"]["body"] is None
        assert captured["input"]["url"].endswith("/api/tags")

    def test_unhealthy_without_sandbox(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = False
        with patch("aios.runtime.ollama.subprocess.run") as mock_run:
            assert adapter.health_check() is False
        mock_run.assert_not_called()

    def test_unhealthy_on_failure(self):
        adapter = OllamaAdapter()
        adapter._ai_jail_installed = True
        with _patch_run(_FakeResult(returncode=1, stderr="nope"), {}):
            assert adapter.health_check() is False


class TestSandboxDetection:
    def test_initialize_requires_ai_jail(self, monkeypatch):
        monkeypatch.setattr("aios.runtime.ollama.shutil.which", lambda _: None)
        adapter = OllamaAdapter()
        adapter.initialize()
        assert adapter.has_sandbox is False
        assert adapter.health_check() is False

    def test_initialize_detects_ai_jail(self, monkeypatch):
        monkeypatch.setattr("aios.runtime.ollama.shutil.which", lambda _: "/usr/bin/ai-jail")
        adapter = OllamaAdapter()
        adapter.initialize()
        assert adapter.has_sandbox is True
        assert adapter.command == "ai-jail python3"

    def test_command_without_ai_jail(self, monkeypatch):
        monkeypatch.setattr("aios.runtime.ollama.shutil.which", lambda _: None)
        adapter = OllamaAdapter()
        adapter.initialize()
        assert "ai-jail" not in adapter.command
