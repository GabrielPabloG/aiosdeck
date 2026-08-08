"""Research package — the Researcher contract and validation."""

from aios.research.models import (
    Finding,
    MemoryCandidate,
    Recommendation,
    ResearchError,
    ResearchResult,
    ResearchSource,
    ResearchTask,
)
from aios.research.schema import (
    research_result_from_dict,
    research_result_to_json,
    validate_research_result,
    validate_research_task,
)

__all__ = [
    "Finding",
    "MemoryCandidate",
    "Recommendation",
    "ResearchError",
    "ResearchResult",
    "ResearchSource",
    "ResearchTask",
    "research_result_from_dict",
    "research_result_to_json",
    "validate_research_result",
    "validate_research_task",
]
