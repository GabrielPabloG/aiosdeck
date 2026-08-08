"""Agent Core Compliance Matrix — the verifiable contract for every agent.

Each entry declares, per agent: the input/output contract, the expected
capabilities, timeout, retry policy, required lifecycle events, and error
behavior. Contract, integration, and architecture tests are all driven by
this matrix, so an architectural rule is expressed as data, not prose.
"""

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent

REQUIRED_TERMINAL_EVENTS = {
    "agent.execution.started",
    "agent.execution.completed",
    "agent.execution.failed",
    "agent.execution.timed_out",
    "agent.execution.cancelled",
    "agent.lifecycle.changed",
}
RETRY_EVENT = "agent.execution.retried"

AGENT_COMPLIANCE_MATRIX: dict[str, dict] = {
    "planner": {
        "agent_class": PlannerAgent,
        "input": "AgentTask(description=<goal>, task_type='plan')",
        "output": "AgentResult(output=<JSON plan>)",
        "capabilities": ["filesystem_read", "ask_user"],
        "timeout": 360.0,
        "retry": {"max_attempts": 2, "retryable_codes": ["TIMEOUT", "RUNTIME_ERROR"]},
        "events": REQUIRED_TERMINAL_EVENTS | {RETRY_EVENT},
        "error_behavior": (
            "runtime exceptions propagate for centralized retry; "
            "invalid JSON output returns a failed AgentResult"
        ),
    },
    "research": {
        "agent_class": ResearchAgent,
        "input": "AgentTask(description=<question>, params={'scope': ...})",
        "output": "AgentResult(output=<research_result JSON>)",
        "capabilities": ["filesystem_read"],
        "timeout": 60.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": (
            "schema violations return a failed AgentResult; "
            "web-without-fetcher degrades to source_unavailable (success)"
        ),
    },
    "developer": {
        "agent_class": DeveloperAgent,
        "input": "AgentTask(description=<task>, task_type=<type>)",
        "output": "AgentResult(output=<runtime output>)",
        "capabilities": ["filesystem_read", "filesystem_write", "shell"],
        "timeout": 600.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": "runtime exceptions propagate for centralized retry",
    },
    "reviewer": {
        "agent_class": ReviewerAgent,
        "input": "AgentTask(params={'target': ..., 'level': ...})",
        "output": "AgentResult(output=<review report JSON>)",
        "capabilities": ["filesystem_read"],
        "timeout": 60.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": "missing target returns a failed AgentResult",
    },
    "tester": {
        "agent_class": TesterAgent,
        "input": "AgentTask(params={'target': ..., 'dry_run': ...})",
        "output": "AgentResult(output=<test report JSON>)",
        "capabilities": ["filesystem_read", "shell"],
        "timeout": 180.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": (
            "missing target returns a failed AgentResult; "
            "test failures stay a successful execution (report carries 'failed')"
        ),
    },
    "documentation": {
        "agent_class": DocumentationAgent,
        "input": "AgentTask(params={'report': ..., 'dry_run': ...})",
        "output": "AgentResult(output=<fragment JSON>)",
        "capabilities": ["filesystem_read", "filesystem_write"],
        "timeout": 30.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": "missing report returns a failed AgentResult",
    },
    "git": {
        "agent_class": GitAgent,
        "input": "AgentTask(task_type=<stage|commit|create_branch|create_tag|push>, params=...)",
        "output": "AgentResult(output=<GitOperation JSON>)",
        "capabilities": ["git"],
        "timeout": 90.0,
        "retry": {"max_attempts": 1, "retryable_codes": ["RUNTIME_ERROR", "TIMEOUT"]},
        "events": REQUIRED_TERMINAL_EVENTS,
        "error_behavior": (
            "non-zero returncode returns a failed AgentResult; "
            "unapproved push is a guarded non-execution (returncode 0)"
        ),
    },
}

AGENT_NAMES = tuple(AGENT_COMPLIANCE_MATRIX)
