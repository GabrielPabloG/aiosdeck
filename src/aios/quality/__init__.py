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

__all__ = [
    "CodeGate",
    "DocumentationGate",
    "GateFinding",
    "GateInput",
    "GateResult",
    "GateStatus",
    "QualityGate",
    "ReleaseGate",
    "SecurityGate",
    "Severity",
    "TestGate",
    "severity_mapper",
]
