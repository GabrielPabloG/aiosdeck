"""Quality pipeline — gate contracts, vocabulary, and concrete gates.

Public API of the quality subsystem:
- ``contracts``: ``GateStatus``, ``Severity``, ``GateInput``, ``GateFinding``,
  ``GateResult``, ``QualityGate`` protocol, ``severity_mapper``
- ``gates``: ``CodeGate``, ``TestGate``, ``SecurityGate``,
  ``DocumentationGate``, ``ReleaseGate``
"""

from aios.quality.contracts import (
    GateFinding,
    GateInput,
    GateResult,
    GateStatus,
    QualityGate,
    Severity,
    severity_mapper,
)
from aios.quality.gates import (
    CodeGate,
    DocumentationGate,
    ReleaseGate,
    SecurityGate,
    TestGate,
)
from aios.quality.policy import (
    DEFAULT_POLICY,
    DecisionResult,
    GateDecision,
    GateOverride,
    resolve_decision,
)

__all__ = [
    "CodeGate",
    "DEFAULT_POLICY",
    "DecisionResult",
    "DocumentationGate",
    "GateDecision",
    "GateFinding",
    "GateInput",
    "GateOverride",
    "GateResult",
    "GateStatus",
    "QualityGate",
    "ReleaseGate",
    "SecurityGate",
    "Severity",
    "TestGate",
    "resolve_decision",
    "severity_mapper",
]
