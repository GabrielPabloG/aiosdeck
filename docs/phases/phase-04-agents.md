# Phase 04 — Agents

**Status**: Proposed
**Date**: 2026-08-02
**Target Version**: v0.2+

## Context

Agents are the workers of AiosDeck. Each agent has a single responsibility, communicates exclusively through events, and executes through the Runtime Adapter. Agents do not share logic. Agents do not store state. Agents load Skills on-demand.

The agent model follows the philosophy: **one agent, one job**. When an agent's responsibilities grow too broad, it is split — never expanded. The first agent (Developer, v0.2) handles everything. By v0.8, the system has eight specialized agents.

Execution infrastructure shared by all LLM-based agents lives in the **AgentExecutor** (v0.5). The Executor wraps each agent's runtime invocation with Event Bus publishing, metrics, and (future) timeout/retry — without knowing anything about agents, prompts, or LLMs.

## Decision

### Agent Protocol

Every agent implements:

```python
class Agent(Protocol):
    name: str
    description: str
    version: str                     # Version when the agent was introduced
    required_capabilities: list[str] # Minimal capabilities needed
    required_skills: list[str]       # Skills loaded before every task

    async def execute(self, task: Task, context: ContextPacket) -> AgentResult: ...
    async def health_check(self) -> bool: ...
    async def initialize(self, bus: EventBus) -> None: ...
    async def shutdown(self) -> None: ...
```

### Agent Lifecycle

```
1. Agent registered with Scheduler
2. Event: agent.started (when first task assigned)
3. Agent prepares execution: builds prompt via PromptBuilder
4. Agent creates ExecutionRequest(invoke=...) and delegates to AgentExecutor
5. AgentExecutor publishes agent.execution.started, invokes Runtime
6. AgentExecutor publishes agent.execution.finished or agent.execution.failed
7. Agent interprets ExecutionOutcome → AgentResult (decides success/failure)
8. Event: agent.completed (success) or agent.errored (failure)
9. Agent returns to idle
```

### Event Contract (All Agents)

Every agent:

**Consumes**:
- `task.created` (relevant type)

**Emits**:
- `agent.started` (on task start)
- `agent.completed` (on success)
- `agent.errored` (on failure)
- `agent.skill_loaded` (optional, for debugging)

### Agent Registry

Agents are registered with the Scheduler by type:

```python
AGENT_REGISTRY = {
    "developer": DeveloperAgent,      # v0.2
    "planner": PlannerAgent,          # v0.6
    "reviewer": ReviewerAgent,        # v0.5
    "coder": CoderAgent,              # v0.8
    "tester": TesterAgent,            # v0.6
    "documentation": DocumentationAgent,  # v0.6
    "git": GitAgent,                  # v0.7
    "researcher": ResearcherAgent,    # v0.8
}
```

### Agent Result

```python
@dataclass
class AgentResult:
    success: bool
    output: str                      # Agent output text
    errors: list[str]                # Non-empty if success=False
    duration_ms: float               # Execution wall-clock time
```

The AgentResult is the agent's interpretation of the neutral ExecutionOutcome returned by AgentExecutor. The Executor reports what happened; the agent decides whether it was success.

### Skill Loading

Before executing a task, the agent loads required Skills:

1. Skills from project manifest (`aios/project.yaml` → `skills:`)
2. Skills required by the agent type (`required_skills` field)
3. Skills are loaded via the Runtime Adapter (OpenCode skill tool)

Skills are additive. The agent's base capabilities are always present. Skills add domain knowledge.

### Capability Model

Every agent declares its minimum capabilities. The Security Manager enforces them at the AiosDeck level. Additionally, the Runtime Adapter (v0.6.1) enforces them at the OpenCode tool level via `OPENCODE_PERMISSION`: read-only agents (Planner, Reviewer) have `edit` and `bash` denied; the `question` tool is denied for all agents in headless mode.

| Agent | filesystem_read | filesystem_write | shell | internet | git | docker |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| Developer | + | + | + | - | + | - |
| Planner | + | - | - | - | - | - |
| Reviewer | + | - | - | - | - | - |
| Coder | + | + | + | - | - | - |
| Tester | + | + | + | - | - | - |
| Documentation | + | + | - | - | - | - |
| Git | + | - | + | - | + | - |
| Researcher | + | - | - | + | - | - |

### Agent Evolution

Agents are introduced incrementally. The system starts with one agent (Developer, v0.2) and splits it as complexity grows:

```
v0.2: Developer (does everything)
       │
v0.4: Developer → Developer + Planner (task decomposition split off)
       │
v0.5: Developer → Coder + Reviewer (review split off)
       │
v0.6: Developer → Coder + Tester + Documentation (testing and docs split off)
       │
v0.7: Developer → Coder + Git (version control split off)
       │
v0.8: Coder remains. Planner, Reviewer, Tester, Documentation, Git, Researcher
       all specialized agents. Developer retired.
```

The Developer agent is the only agent that violates "one agent, one job." It exists as a temporary bootstrap until specialization is warranted.

## Consequences

### Positive

- **Simple interface**: Three methods + event handlers. Easy to implement new agents.
- **Gradual specialization**: Agents split when needed, not before.
- **Security integration**: Every agent is constrained by capabilities. No agent gets blanket access.
- **Testability**: Agents can be tested with mock Runtime Adapter and Context Packet.

### Negative

- **Skill dependency**: Agents rely on Skills for domain knowledge. Missing Skills mean poor output.
- **Sequential execution**: v0.2–v0.7 run one agent at a time. Parallel agents require v0.8 Scheduler.
- **Context dependency**: Agent output quality depends on Context Engine accuracy.

### Neutral

- Agent implementations are Python classes. Custom agents can be added via the Plugin System (v0.9).
- The Developer agent is intentionally monolithic. It proves the architecture before specialization.

## Implementation Notes

- [ ] Implement `agents/base.py` — Agent protocol + AgentResult dataclass
- [ ] Implement agent registry in `agents/__init__.py`
- [ ] Each agent must implement: name, version, required_capabilities, required_skills, execute, health_check
- [ ] Agent execution must log: task ID, duration, files changed, success/failure
- [ ] Skill loading must happen before task execution, not during
- [ ] Agent errors must emit `agent.errored`, not crash the Scheduler
- [ ] Test: agent registry contains all defined agents
- [ ] Test: agent execute with mock runtime returns AgentResult
- [ ] Test: agent with missing capability → Security Manager denies during execution
- [ ] Test: agent with missing skill → warning logged, execution continues
