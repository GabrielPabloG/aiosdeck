"""Runtime Engine — manages the runtime adapter lifecycle and model routing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aios.routing.models import RouteInput
from aios.runtime.diagnostics import RuntimeDiagnostic
from aios.runtime.opencode import OpenCodeAdapter

if TYPE_CHECKING:
    from aios.routing import ModelRouter

logger = logging.getLogger("aios.runtime")


class RouteFallbackExhausted(RuntimeError):
    """All models in the fallback chain failed."""


class RuntimeEngine:
    name = "runtime"

    def __init__(
        self,
        adapter: OpenCodeAdapter | None = None,
        router: ModelRouter | None = None,
        bus: object | None = None,
        config: object | None = None,
    ) -> None:
        self.adapter = adapter or OpenCodeAdapter()
        self._router = router
        self._bus = bus
        self._config = config
        self.runtime_diagnostics: RuntimeDiagnostic | None = None

    @property
    def router(self) -> ModelRouter | None:
        return self._router

    def initialize(self) -> None:
        self.adapter.initialize()

    def health_check(self) -> bool:
        return self.adapter.health_check()

    def diagnose(self) -> RuntimeDiagnostic | None:
        """Run adapter-specific deep diagnostics without changing health_check()."""
        diagnose = getattr(self.adapter, "diagnose", None)
        if diagnose is None:
            return None
        provider = ""
        model = ""
        source = "default"
        if self._router is not None:
            decision = self._router.route(RouteInput(agent=""))
            provider = decision.provider
            model = decision.model
            route_sources = getattr(self._config, "_sources", {})
            source = route_sources.get("routing.default_model", "default")
        elif self._config is not None:
            model_config = getattr(self._config, "model", None)
            if model_config is not None:
                provider = getattr(model_config, "default", "")
                model = f"{provider}/{getattr(model_config, 'ollama_model', '')}"
                source = getattr(self._config, "_sources", {}).get("model.default", "default")
        return diagnose(provider=provider, model=model, source=source)

    def shutdown(self) -> None:
        self.adapter.shutdown()

    def set_event_bus(self, bus: object) -> None:
        self._bus = bus

    @property
    def command(self) -> str:
        return self.adapter.command

    @property
    def has_sandbox(self) -> bool:
        return self.adapter.has_sandbox

    def execute(  # noqa: PLR0913
        self,
        prompt: str,
        skills: list[str],
        capabilities: list[str] | None = None,
        permissions=None,
        *,
        agent: str = "",
        task_type: str = "",
        complexity: str = "medium",
        context_size: int = 0,
        model: str = "",
    ) -> str:
        decision_model = ""
        decision_variant = ""
        fallback_chain: list[dict] = []
        source = "legacy"
        reason = ""

        if model:
            decision_model = model
            source = "override"
            reason = "explicit_override"
        elif self._router is not None:
            route_input = RouteInput(
                agent=agent,
                task_type=task_type or "code",
                complexity=complexity or "medium",
                context_size=context_size,
            )
            decision = self._router.route(route_input)
            decision_model = decision.model
            decision_variant = decision.variant
            fallback_chain = decision.fallback_chain
            source = decision.source
            reason = decision.reason

        models_to_try = [
            {
                "model": decision_model,
                "variant": decision_variant,
                "provider": "",
                "reason": reason,
            }
        ]
        models_to_try.extend(fallback_chain)

        last_error: Exception | None = None
        for attempt in models_to_try:
            try:
                result = self.adapter.execute(
                    prompt,
                    skills,
                    capabilities,
                    permissions,
                    model=attempt["model"],
                    variant=attempt.get("variant", ""),
                )
                self._emit_route_event(
                    provider=attempt.get("provider", ""),
                    model=attempt["model"],
                    variant=attempt.get("variant", ""),
                    reason=attempt.get("reason", ""),
                    source=source,
                    context_size=context_size,
                    agent=agent,
                    task_type=task_type,
                    complexity=complexity,
                    fallback_used=(attempt is not models_to_try[0]),
                    fallback_reason=self._fallback_reason(last_error) if last_error else "",
                )
                return result
            except (RuntimeError, TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "Model %s failed: %s — trying next fallback",
                    attempt["model"],
                    exc,
                )
                continue

        raise RouteFallbackExhausted(
            f"All models exhausted for agent '{agent}'. Last error: {last_error}"
        )

    def _emit_route_event(  # noqa: PLR0913, PLR0917
        self,
        provider: str,
        model: str,
        variant: str,
        reason: str,
        source: str,
        context_size: int,
        agent: str,
        task_type: str,
        complexity: str,
        fallback_used: bool,
        fallback_reason: str,
    ) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(
                "runtime.route_selected",
                {
                    "agent": agent,
                    "task_type": task_type,
                    "complexity": complexity,
                    "provider": provider,
                    "model": model,
                    "variant": variant,
                    "reason": reason,
                    "context_size": context_size,
                    "source": source,
                    "fallback_used": fallback_used,
                    "fallback_reason": fallback_reason,
                },
            )
        except Exception as exc:
            logger.debug("Failed to emit route event: %s", exc)

    @staticmethod
    def _fallback_reason(error: Exception | None) -> str:
        if error is None:
            return ""
        if isinstance(error, TimeoutError):
            return "timeout"
        msg = str(error).lower()
        if "budget" in msg:
            return "budget_exceeded"
        return "unavailable"
