"""Ollama runtime adapter — local models through the ai-jail sandbox.

Generation-only adapter: every model call runs inside ``ai-jail`` (the
sandbox is a non-negotiable security boundary for runtime subprocesses). A
missing sandbox is a hard failure — there is no un-sandboxed fallback.

Requests target Ollama's native ``/api/chat`` endpoint with JSON mode forced
(``format: "json"``) and a generous context window (``num_ctx``) so strict
structured outputs (planner plans) parse reliably.

The adapter exposes no tool surface (no bash/edit/network tools); ``skills``,
``capabilities`` and ``permissions`` are accepted for contract parity with
:class:`~aios.runtime.opencode.OpenCodeAdapter` but have no effect on
generation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("aios.runtime.ollama")

_DEFAULT_HOST = "http://localhost:11434"
_DEFAULT_MODEL = "llama3"
_NUM_CTX = 16384

_SCRIPT = """\
import json, sys, urllib.request
payload = json.load(sys.stdin)
if payload["body"] is None:
    req = urllib.request.Request(payload["url"])
else:
    req = urllib.request.Request(
        payload["url"],
        data=json.dumps(payload["body"]).encode(),
        headers={"Content-Type": "application/json"},
    )
with urllib.request.urlopen(req, timeout=600) as resp:
    print(json.dumps(json.load(resp)))
"""


class OllamaAdapter:
    """Local generation through Ollama, always inside ai-jail."""

    name = "ollama"
    version = "1.0"

    def __init__(self, *, host: str | None = None, model: str | None = None) -> None:
        self._host = host or os.environ.get("AIOS_OLLAMA_HOST", _DEFAULT_HOST)
        self._model = model or os.environ.get("AIOS_OLLAMA_MODEL", _DEFAULT_MODEL)
        self._ai_jail_installed = False
        self._resolved_command = "ai-jail python3"

    def initialize(self) -> None:
        self._ai_jail_installed = shutil.which("ai-jail") is not None
        if not self._ai_jail_installed:
            self._resolved_command = "python3 (not found)"
            logger.warning("ai-jail not found. OllamaAdapter cannot run unsandboxed.")

    def health_check(self) -> bool:
        if not self._ai_jail_installed:
            return False
        try:
            data = json.loads(self._run_sandboxed({"url": f"{self._host}/api/tags", "body": None}))
            return isinstance(data, dict) and "models" in data
        except (RuntimeError, ValueError, subprocess.SubprocessError):
            return False

    def shutdown(self) -> None:
        pass

    @property
    def command(self) -> str:
        return self._resolved_command

    @property
    def has_sandbox(self) -> bool:
        return self._ai_jail_installed

    def execute(  # noqa: PLR0913 - mirrors the RuntimeAdapter contract
        self,
        prompt: str,
        skills: list[str],
        capabilities: list[str] | None = None,
        permissions=None,
        *,
        model: str = "",
        variant: str = "",
    ) -> str:
        del skills, capabilities, permissions, variant
        if not self._ai_jail_installed:
            raise RuntimeError("OllamaAdapter requires ai-jail (sandbox is mandatory)")
        body = {
            "model": self._model_from(model),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"num_ctx": _NUM_CTX},
        }
        try:
            data = json.loads(self._run_sandboxed({"url": f"{self._host}/api/chat", "body": body}))
        except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Ollama response missing message.content: {data}")
        return content

    def _model_from(self, model: str) -> str:
        if not model:
            return self._model
        _, sep, name = model.partition("/")
        return name if sep and name else model

    def _run_sandboxed(self, payload: dict) -> str:
        result = subprocess.run(
            ["ai-jail", "--", "python3", "-c", _SCRIPT],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "unknown error"
            raise RuntimeError(f"Ollama sandbox exited with code {result.returncode}: {stderr}")
        return result.stdout.strip()
