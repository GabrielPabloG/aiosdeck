"""Security Engine — skeleton for v0.1.

In v0.1, the Security Manager is a skeleton that loads policy files
and initializes the audit logger. Full enforcement is implemented in v0.6.
"""

import logging
from pathlib import Path

logger = logging.getLogger("aios.security")


class SecurityEngine:
    name = "security"

    def __init__(self, project_path: Path | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._policies_loaded = False
        self._audit_path: Path | None = None

    def initialize(self) -> None:
        self._load_policies()
        self._init_audit_log()

    def health_check(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

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
