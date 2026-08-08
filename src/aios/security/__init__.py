"""Security Engine — skeleton for v0.1.

In v0.1, the Security Manager is a skeleton that loads policy files
and initializes the audit logger. Full enforcement is implemented in v0.6.
"""

import logging
from pathlib import Path

from aios.security.actions import (
    ASK_USER_ACTION,
    CAPABILITY_ACTIONS,
    DEFAULT_INTENTS,
    FILESYSTEM_DELETE,
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    GIT_BRANCH,
    GIT_COMMIT,
    GIT_PUSH,
    GIT_TAG,
    NETWORK_ACCESS,
    RELEASE_PUBLISH,
    SHELL_EXECUTE,
    WORKFLOW_INTENT,
    expand,
)
from aios.security.capabilities import CapabilityEnforcer
from aios.security.contracts import (
    EffectivePermissions,
    IntentPolicy,
    SecurityDecision,
)
from aios.security.resolver import decide, effective_permissions

logger = logging.getLogger("aios.security")

__all__ = [
    "ASK_USER_ACTION",
    "CAPABILITY_ACTIONS",
    "CapabilityEnforcer",
    "DEFAULT_INTENTS",
    "EffectivePermissions",
    "FILESYSTEM_DELETE",
    "FILESYSTEM_READ_ACTION",
    "FILESYSTEM_WRITE_ACTION",
    "GIT_BRANCH",
    "GIT_COMMIT",
    "GIT_PUSH",
    "GIT_TAG",
    "IntentPolicy",
    "NETWORK_ACCESS",
    "RELEASE_PUBLISH",
    "SHELL_EXECUTE",
    "SecurityDecision",
    "SecurityEngine",
    "WORKFLOW_INTENT",
    "decide",
    "effective_permissions",
    "expand",
]


class SecurityEngine:
    name = "security"

    def __init__(self, project_path: Path | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._policies_loaded = False
        self._audit_path: Path | None = None
        self._enforcer = CapabilityEnforcer()

    def initialize(self) -> None:
        self._load_policies()
        self._init_audit_log()

    def health_check(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def validate_agent_capabilities(self, agent) -> bool:
        """Validate an agent's declared capabilities against the canonical policy."""
        self._enforcer.validate(agent)
        return True

    def _load_policies(self) -> None:
        policies_dir = self._project_path / "aios" / "policies"
        capabilities_policy = policies_dir / "agent_capabilities.yaml"

        if capabilities_policy.exists():
            logger.info("Security policy loaded: %s", capabilities_policy)
            self._policies_loaded = True
        else:
            logger.debug("No security policies found at %s", policies_dir)
            self._policies_loaded = False

    def _init_audit_log(self) -> None:
        self._audit_path = Path.home() / ".local" / "share" / "aiosdeck" / "audit.log"
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            self._audit_path.touch(exist_ok=True)
        except OSError:
            self._audit_path = None
            logger.debug("Audit log unavailable (filesystem restriction)")
