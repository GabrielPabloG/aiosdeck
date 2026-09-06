"""OpenCode runtime adapter — always invoked through ai-jail."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from aios.agents.models import AgentResult
from aios.runtime.diagnostics import RuntimeDiagnostic
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
)
from aios.security.contracts import EffectivePermissions

logger = logging.getLogger("aios.runtime.opencode")

# Bash command policy. opencode's last-match-wins rule means the deny rules must
# precede the run allowlist so an explicit deny always survives ``--auto``.
_BASH_RULES: dict[str, str] = {
    "*": "deny",
    "git push *": "deny",
    "git tag *": "deny",
    "rm -rf *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git branch *": "allow",
    "git commit *": "allow",
    "grep *": "allow",
    "ruff *": "allow",
    "python *": "allow",
    "pytest *": "allow",
}

_WRITE_AGENT = "build"

_TURN_KINDS = frozenset({"tool", "text", "reasoning", "unknown"})


@dataclass
class TurnEvent:
    """One step within an OpenCode --auto execution."""

    index: int
    kind: str  # "tool" | "text" | "reasoning" | "unknown"
    tool_name: str | None = None
    duration_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0


@dataclass
class AgentMetrics:
    """Structured metrics extracted from OpenCode JSONL output."""

    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)
    tool_durations_ms: list[float] = field(default_factory=list)
    llm_turns: int = 0
    total_cost: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)
    turns: list[TurnEvent] = field(default_factory=list)
    repeated_tool_calls: int = 0
    exit_reason: str = "stop"


def _parse_jsonl(output: str) -> tuple[str, AgentMetrics]:  # noqa: PLR0912, PLR0915
    """Parse OpenCode ``--format json`` JSONL output into text and metrics.

    Pure function — no side effects, easy to test. Returns the final text
    output and an :class:`AgentMetrics` summary. Tolerant of unknown events
    and malformed lines.
    """
    metrics = AgentMetrics()
    text_parts: list[str] = []
    tool_durations: dict[str, float] = {}
    tool_counts: dict[str, int] = {}
    turns: list[TurnEvent] = []

    # Per-turn state tracking
    current_turn_index = -1
    current_turn_start = 0
    current_turn_kind = "unknown"
    current_turn_tool: str | None = None
    current_turn_tokens_in = 0
    current_turn_tokens_out = 0
    current_turn_cost = 0.0
    prev_tool_call: tuple[str, str] | None = None  # (tool_name, input_summary)

    def _finalize_turn():
        nonlocal current_turn_start, current_turn_kind, current_turn_tool
        nonlocal current_turn_tokens_in, current_turn_tokens_out, current_turn_cost
        if current_turn_index < 0:
            return
        duration = 0.0
        if current_turn_start > 0:
            # duration is computed from event timestamps, not here
            pass
        turns.append(
            TurnEvent(
                index=current_turn_index,
                kind=current_turn_kind,
                tool_name=current_turn_tool,
                duration_ms=duration,
                tokens_in=current_turn_tokens_in,
                tokens_out=current_turn_tokens_out,
                cost=current_turn_cost,
            )
        )
        current_turn_kind = "unknown"
        current_turn_tool = None
        current_turn_tokens_in = 0
        current_turn_tokens_out = 0
        current_turn_cost = 0.0

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        part = event.get("part", {})
        event_ts = event.get("timestamp", 0)

        if event_type == "step_start":
            _finalize_turn()
            current_turn_index += 1
            current_turn_start = event_ts

        elif event_type == "text":
            text = part.get("text", "")
            if text:
                text_parts.append(text)
            if current_turn_kind != "tool":
                current_turn_kind = "text"

        elif event_type == "reasoning":
            if current_turn_kind == "unknown":
                current_turn_kind = "reasoning"

        elif event_type == "tool_use":
            tool_name = part.get("tool", "")
            state = part.get("state", {})
            if state.get("status") == "completed":
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                current_turn_kind = "tool"
                current_turn_tool = tool_name
                timing = state.get("time", {})
                start = timing.get("start", 0)
                end = timing.get("end", 0)
                if start and end:
                    tool_durations[tool_name] = tool_durations.get(tool_name, 0.0) + (
                        end - start
                    )
                    # Update turn duration from tool timing
                    if current_turn_index >= 0 and turns:
                        turns[-1].duration_ms += end - start
                # Track repeated tool calls
                input_data = state.get("input", {})
                input_summary = json.dumps(input_data, sort_keys=True, default=str)[:200]
                current_call = (tool_name, input_summary)
                if prev_tool_call == current_call:
                    metrics.repeated_tool_calls += 1
                prev_tool_call = current_call

        elif event_type == "step_finish":
            tokens_part = part.get("tokens", {})
            if tokens_part:
                t_in = tokens_part.get("input", 0)
                t_out = tokens_part.get("output", 0)
                metrics.tokens = {
                    "input": t_in,
                    "output": t_out,
                    "reasoning": tokens_part.get("reasoning", 0),
                    "cache_read": tokens_part.get("cache", {}).get("read", 0),
                    "cache_write": tokens_part.get("cache", {}).get("write", 0),
                }
                current_turn_tokens_in = t_in
                current_turn_tokens_out = t_out
            cost_val = part.get("cost", 0.0)
            metrics.total_cost += cost_val
            current_turn_cost = cost_val
            reason = part.get("reason", "")
            if reason and reason != "tool-calls":
                metrics.exit_reason = reason

    _finalize_turn()
    metrics.tool_calls = sum(tool_counts.values())
    metrics.tool_names = [
        name for name, _ in sorted(tool_counts.items(), key=lambda x: -x[1])
    ]
    metrics.tool_durations_ms = [
        tool_durations.get(name, 0.0) for name in metrics.tool_names
    ]
    metrics.llm_turns = len(turns)
    metrics.turns = turns

    text = "\n".join(text_parts)
    return text, metrics


class OpenCodeAdapter:
    name = "opencode"
    version = "1.0"

    def __init__(self) -> None:
        self._opencode_installed = False
        self._ai_jail_installed = False
        self._initialized = False
        self._resolved_command = "opencode"
        self._permission_cache: dict[tuple[str, ...], str] = {}

    def initialize(self) -> None:
        self._opencode_installed = shutil.which("opencode") is not None
        self._ai_jail_installed = shutil.which("ai-jail") is not None
        self._resolve_command()
        self._initialized = True

    def health_check(self) -> bool:
        return self._opencode_installed

    def shutdown(self) -> None:
        pass

    @property
    def command(self) -> str:
        return self._resolved_command

    @property
    def has_sandbox(self) -> bool:
        return self._ai_jail_installed

    def _resolve_command(self) -> None:
        if not self._opencode_installed:
            self._resolved_command = "opencode (not found)"
            return

        if self._ai_jail_installed:
            self._resolved_command = "ai-jail opencode"
        else:
            self._resolved_command = "ai-jail opencode (not found)"
            logger.warning("ai-jail not found. OpenCode execution is disabled.")

    def diagnose(  # noqa: PLR0911
        self,
        *,
        provider: str,
        model: str,
        source: str = "default",
    ) -> RuntimeDiagnostic:
        """Run the deep OpenCode check inside the same sandbox as execution."""
        checks = {
            "opencode": self._opencode_installed,
            "ai_jail": self._ai_jail_installed,
        }
        if not self._opencode_installed:
            return RuntimeDiagnostic(
                False,
                "opencode_missing",
                "OpenCode executable was not found.",
                source,
                provider,
                model,
                checks,
                ["Install OpenCode and ensure it is available on PATH."],
            )
        if not self._ai_jail_installed:
            return RuntimeDiagnostic(
                False,
                "ai_jail_missing",
                "ai-jail is required to run OpenCode safely.",
                source,
                provider,
                model,
                checks,
                ["Install ai-jail; OpenCode will not run without the sandbox."],
            )
        if not provider:
            return RuntimeDiagnostic(
                False,
                "provider_missing",
                "No provider was resolved for the runtime.",
                source,
                provider,
                model,
                checks,
                ["Configure routing.default_provider."],
            )
        if not model or model.rstrip("/") == provider:
            return RuntimeDiagnostic(
                False,
                "model_missing",
                f"No model was resolved for provider '{provider}'.",
                source,
                provider,
                model,
                checks,
                [f"Configure routing.default_model or run opencode models {provider}."],
            )

        checks["endpoint"] = False
        checks["model"] = False

        try:
            result = subprocess.run(
                ["ai-jail", "opencode", "models", provider],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RuntimeDiagnostic(
                False,
                "endpoint_unreachable",
                f"Could not query provider '{provider}' from inside ai-jail: {exc}",
                source,
                provider,
                model,
                checks,
                [f"Check the {provider} endpoint and run opencode models {provider}."],
            )

        if result.returncode != 0:
            detail = self._redact_detail(result.stderr or "unknown error")
            return RuntimeDiagnostic(
                False,
                "endpoint_unreachable",
                f"Provider '{provider}' is not reachable from inside ai-jail: {detail}",
                source,
                provider,
                model,
                checks,
                [f"Check the {provider} endpoint and run opencode models {provider}."],
            )

        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        model_name = model.split("/", 1)[-1]
        if model_name not in output and model not in output:
            return RuntimeDiagnostic(
                False,
                "model_unavailable",
                f"Model '{model}' was not reported by provider '{provider}'.",
                source,
                provider,
                model,
                checks,
                [f"Run opencode models {provider} and configure an available model."],
            )
        checks["endpoint"] = True
        checks["model"] = True
        return RuntimeDiagnostic(
            True,
            "ok",
            f"OpenCode provider '{provider}' and model '{model}' are available.",
            source,
            provider,
            model,
            checks,
        )

    def execute(  # noqa: PLR0913, PLR0912, PLR0915
        self,
        prompt: str,
        skills: list[str],
        capabilities: list[str] | None = None,
        permissions: EffectivePermissions | None = None,
        *,
        model: str = "",
        variant: str = "",
        max_steps: int = 0,
    ) -> AgentResult:
        args = self._resolved_command.split()
        args.extend(["run", prompt, "--format", "json"])

        if model:
            args.extend(["-m", model])
        if variant:
            args.extend(["--variant", variant])

        if self._is_write_capable(permissions, capabilities):
            args.extend(["--agent", _WRITE_AGENT])

        args.append("--auto")

        if not self._opencode_installed:
            raise RuntimeError(f"Runtime not available: {self._resolved_command}")
        if self._initialized and not self._ai_jail_installed:
            raise RuntimeError("Runtime requires ai-jail (sandbox is mandatory)")

        env = os.environ.copy()
        if permissions is not None:
            permissions_json = self._build_permissions(permissions)
        else:
            permissions_json = self._build_permissions(capabilities or [])
        env["OPENCODE_PERMISSION"] = permissions_json

        tmp_config_dir = None
        if max_steps > 0:
            try:
                tmp_config_dir = tempfile.mkdtemp(prefix="aios_oc_")
                oc_dir = Path(tmp_config_dir) / ".opencode"
                oc_dir.mkdir(parents=True, exist_ok=True)
                config_path = oc_dir / "opencode.json"
                config_path.write_text(
                    json.dumps({"agent": {"build": {"maxSteps": max_steps}}}),
                    encoding="utf-8",
                )
                args.extend(["--dir", tmp_config_dir])
            except OSError:
                logger.warning("Could not create temp config for max_steps=%d", max_steps)
                tmp_config_dir = None

        try:
            kwargs: dict = {
                "text": True,
                "timeout": 600,
                "env": env,
                "capture_output": True,
            }

            result = subprocess.run(args, check=False, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Runtime execution timed out after 600s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"Runtime command not found: {self._resolved_command}") from exc
        finally:
            if tmp_config_dir is not None:
                shutil.rmtree(tmp_config_dir, ignore_errors=True)

        if result.returncode != 0:
            stderr = (
                self._redact_detail(result.stderr.strip()) if result.stderr else "unknown error"
            )
            raise RuntimeError(f"Runtime exited with code {result.returncode}: {stderr}")

        stdout = result.stdout.strip() if result.stdout else ""
        try:
            text, metrics = _parse_jsonl(stdout)
        except Exception:
            logger.warning("JSONL parser failed; falling back to raw stdout")
            text = stdout
            metrics = AgentMetrics()

        return AgentResult(
            success=True,
            output=text,
            tool_calls=metrics.tool_calls,
            tool_names=metrics.tool_names,
            tool_durations_ms=metrics.tool_durations_ms,
            llm_turns=metrics.llm_turns,
            total_cost=metrics.total_cost,
            tokens=metrics.tokens,
            model=model,
            steps_used=metrics.llm_turns,
            repeated_tool_calls=metrics.repeated_tool_calls,
            turn_sequence=[t.tool_name or t.kind for t in metrics.turns],
            exit_reason=metrics.exit_reason,
        )

    @staticmethod
    def _is_write_capable(
        permissions: EffectivePermissions | list[str] | None,
        capabilities: list[str] | None,
    ) -> bool:
        """Whether the granted access includes write or shell execution.

        Mirrors the resolution order of ``_build_permissions``: a resolved
        ``EffectivePermissions`` (or frozenset of granular actions) wins; a
        plain list falls back to the coarse capability names. Selecting the
        runtime's write-capable agent keeps the session capability aligned
        with the permissions AiosDeck granted — a plan-only session could
        otherwise answer with text and never touch files.
        """
        if isinstance(permissions, EffectivePermissions):
            allowed = permissions.allowed
        elif isinstance(permissions, frozenset):
            allowed = permissions
        else:
            caps = permissions if isinstance(permissions, list) else capabilities or []
            return "filesystem_write" in caps or "shell" in caps
        return FILESYSTEM_WRITE_ACTION in allowed or SHELL_EXECUTE in allowed

    @staticmethod
    def _redact_detail(detail: str) -> str:
        """Keep provider errors useful without exposing common secret fields."""
        secret_markers = ("token", "api_key", "apikey", "password", "secret", "authorization")
        safe_lines = [
            line
            for line in detail.splitlines()
            if not any(marker in line.lower() for marker in secret_markers)
        ]
        return "\n".join(safe_lines).strip() or "provider returned an error"

    def _build_permissions(
        self,
        effective: EffectivePermissions | list[str] | None = None,
        capabilities: list[str] | None = None,
    ) -> str:
        """Build the ``OPENCODE_PERMISSION`` JSON.

        A resolved ``EffectivePermissions`` maps each granular action to the
        least-privilege tool policy. A list (or nothing) is the legacy coarse
        capability path, byte-identical to previous output.
        """
        if isinstance(effective, EffectivePermissions):
            return self._build_effective_permissions(effective)
        if isinstance(effective, frozenset):
            return self._build_effective_permissions(EffectivePermissions(allowed=effective))
        return self._build_legacy_permissions(
            effective if isinstance(effective, list) else capabilities or []
        )

    def _build_legacy_permissions(self, capabilities: list[str]) -> str:
        key = ("legacy",) + tuple(sorted(capabilities))
        if key in self._permission_cache:
            return self._permission_cache[key]

        permissions: dict[str, str] = {
            "question": "deny",
        }

        if "filesystem_write" not in capabilities and "shell" not in capabilities:
            permissions["edit"] = "deny"
            permissions["bash"] = "deny"

        json_str = json.dumps(permissions)
        self._permission_cache[key] = json_str
        return json_str

    def _build_effective_permissions(self, effective: EffectivePermissions) -> str:
        key = ("effective",) + tuple(sorted(effective.allowed))
        if key in self._permission_cache:
            return self._permission_cache[key]

        allowed = effective.allowed
        read = FILESYSTEM_READ_ACTION in allowed
        write = FILESYSTEM_WRITE_ACTION in allowed
        shell = SHELL_EXECUTE in allowed
        network = NETWORK_ACCESS in allowed

        permissions: dict[str, str | dict[str, str]] = {
            "question": "deny",
            "read": "allow" if read else "deny",
            "glob": "allow" if read else "deny",
            "grep": "allow" if read else "deny",
            "edit": "allow" if write else "deny",
            "webfetch": "allow" if network else "deny",
            "websearch": "allow" if network else "deny",
        }
        permissions["bash"] = _BASH_RULES if shell else "deny"

        json_str = json.dumps(permissions)
        self._permission_cache[key] = json_str
        return json_str
