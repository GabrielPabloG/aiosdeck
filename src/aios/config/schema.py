"""Configuration dataclasses."""

from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    adapter: str = "opencode"
    sandbox: str = "ai-jail"
    command: str = "ai-jail opencode"


@dataclass
class ModelConfig:
    default: str = "ollama"
    ollama_model: str = "llama3"
    ollama_host: str = "http://localhost:11434"


@dataclass
class MemoryConfig:
    enabled: bool = True
    path: str = "~/.local/share/aiosdeck/memory.db"


@dataclass
class SecurityConfig:
    enabled: bool = True
    policies_dir: str = "aios/policies"


@dataclass
class QualityConfig:
    enabled: bool = True
    auto_detect: bool = True
    environment: str = "dev"
    policy: dict[str, list[str]] = field(default_factory=dict)
    overrides: list[dict] = field(default_factory=list)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    audit_path: str = "~/.local/share/aiosdeck/audit.log"


@dataclass
class UIConfig:
    theme: str = "ocean"
    accent_intensity: float = 0.8
    compact: bool = False
    refresh_interval: float = 2.0
    backlog_mode: str = "text"


@dataclass
class LearningConfig:
    enabled: bool = True
    auto_capture: bool = True
    confidence_threshold: float = 0.5
    min_evidence: int = 1
    recurrence_threshold: int = 2
    policy: dict[str, str] = field(default_factory=dict)


@dataclass
class RouteConfig:
    enabled: bool = True
    default_provider: str = "ollama"
    default_model: str = "llama3"
    default_variant: str = ""
    rules: list[dict] = field(default_factory=list)
    cost_cap: float = 0.0
    context_limits: dict[str, int] = field(default_factory=dict)
    fallback_providers: list[dict] = field(default_factory=list)


@dataclass
class ProjectConfig:
    name: str = ""
    directory: str = "~/projects"
    skills: list[str] = field(default_factory=list)


@dataclass
class AiosDeckConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    routing: RouteConfig = field(default_factory=RouteConfig)

    _sources: dict[str, str] = field(default_factory=dict, repr=False)
