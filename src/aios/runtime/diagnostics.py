"""Structured, serializable runtime diagnostics."""

from dataclasses import dataclass, field


@dataclass
class RuntimeDiagnostic:
    """Result of an explicit, potentially slow runtime preflight."""

    healthy: bool
    code: str
    message: str
    source: str = "default"
    provider: str = ""
    model: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "status": "healthy" if self.healthy else "unhealthy",
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "provider": self.provider,
            "model": self.model,
            "checks": dict(self.checks),
            "suggestions": list(self.suggestions),
        }
