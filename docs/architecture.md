# Architecture

**Status**: Accepted
**Date**: 2026-08-04

## Context

AiosDeck coordinates multiple subsystems — agents, memory, scheduling, security, runtime — into a coherent platform. The architecture must support the nine philosophy principles while remaining simple enough to implement incrementally. Every component has a single responsibility, communicates only through events, and can be replaced independently.

The architecture follows a **hub-and-spoke** model: the Kernel is the hub, dispatching events to specialized engines arranged as spokes. No spoke talks directly to another spoke.

## Decision

### System Block Diagram

```
                              User
                               │
                               ▼
                         AiosDeck CLI (aios)
                               │
                               ▼
                             Kernel
                               │
                       Event Dispatcher
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
          Scheduler         Memory           Context
              │                │                │
              └────────────────┼────────────────┘
                               │
                           Task Queue
                               │
                       Security Manager
              ┌────────────────┼────────────────┐
              │ Policy Engine                    │
              │ Capability Manager               │
              │ Secret Manager                   │
              │ Prompt Firewall                  │
              │ Audit Logger                     │
              │ Approval Gates                   │
              └────────────────┼────────────────┘
                               │
                       Quality Pipeline
              ┌────────┬───┴───┬────────┬────────┐
              ▼        ▼       ▼        ▼        ▼
           Format    Lint   Tests  Security  AI Arch
                                               │
                                     Documentation Review
                               │
               ┌────────────────┼─────────────────┐
               ▼                ▼                  ▼
            Planner          Coder            Reviewer
               │                │                  │
               │  (loads Skills from OpenCode      │
               │   skill tool on-demand)           │
               │                │                  │
               └────────────────┼──────────────────┘
                                │
                        AgentExecutor
                                │
                         Runtime Adapter
                               │
                  OpenCode (via ai-jail)
                               │
                Ollama / GPT / Gemini / Claude
```

### Component Responsibility Matrix

| Component | Responsibility | Event Bus Role | Phase |
|-----------|---------------|----------------|-------|
| **CLI** | Entry point. Thin dispatcher via Command Registry. Parses args and renders `RunResult`; owns zero pipeline logic. | Producer | v0.1 |
| **Kernel** | Bootstrap, lifecycle, dispatches events to engines. Canonical `run()` entry point routes tasks to planner/workflow. | Hub | v0.1 |
| **Event Dispatcher** | Routes events between components. Pub/sub with topics. | Core infrastructure | v0.1 |
| **Scheduler** | Manages the kanban board: boards/cards/subtasks, column flow (Backlog→Done), TDD gate enforcement, sprint progress rendering. Persistent via SQLite. | Consumer + Producer | v0.8 (kanban engine) |
| **Memory Engine** | Persistent storage of conventions, decisions, patterns, session history. | Consumer + Producer | v0.3 |
| **Context Engine** | Detects project characteristics, assembles enriched context for agents. | Consumer + Producer | v0.1 |
| **Security Manager** | Enforces zero-trust policies, manages capabilities, filters prompts, logs audits. | Interceptor | v0.1 (skeleton), v0.6 (full) |
| **Quality Pipeline** | Executes automated checks (format, lint, tests, security, AI review, docs). | Consumer + Producer | v0.6 |
| **Runtime Adapter** | Abstracts execution environment. Enforces headless tool permissions via OPENCODE_PERMISSION. | Consumer | v0.1 |
| **AgentExecutor** | Generic execution guardrail. Wraps agent operations with Event Bus, logging, timeout, retry. | Consumer + Producer | v0.5 |
| **Agents** | Specialized workers. Each receives a task and produces a result via the Runtime. | Consumer + Producer | v0.2+ |
| **Workflow Engine** | Orchestrates complex pipelines across multiple agents and gates. | Consumer + Producer | v0.7 |

### Event Bus Topology

All communication between components flows through the Event Bus. Components publish to **topics** and subscribe to topics they care about.

```
Kernel ──► dispatcher ──► topics:
                            │
                            ├── system.shutdown
                            ├── session.start
                            ├── context.detected
                            ├── memory.updated
                            ├── task.created
                            ├── task.completed
                            ├── task.failed
                            ├── agent.started
                             ├── agent.completed
                             ├── agent.errored
                             ├── agent.skill_loaded
                             ├── agent.execution.started
                             ├── agent.execution.finished
                             ├── agent.execution.failed
                             ├── quality.passed
                            ├── quality.failed
                            ├── security.violation
                            ├── approval.requested
                            └── audit.logged
```

Events are fire-and-forget. Producers do not know consumers. Consumers do not know producers. The dispatcher is the only component that knows all routes.

### Python Package Layout

```
aiosdeck/
├── __init__.py
├── __main__.py                  # python -m aiosdeck
│
├── core/                        # Kernel + CLI
│   ├── __init__.py
│   ├── kernel.py                # Bootstrap, lifecycle, dispatcher
│   ├── console.py               # Dashboard rendering
│   └── task.py                  # Task dataclass
│
├── cli/                         # CLI surface (v0.6.1)
│   ├── __init__.py
│   ├── main.py                  # Thin dispatcher — reads COMMANDS, resolves aliases
│   ├── commands.py              # Command dataclass + COMMANDS registry
│   └── completion.py            # Autocomplete engine consuming registry
│
├── context/                     # Context Engine
│   ├── __init__.py
│   ├── engine.py                # Orchestrates detection and assembly
│   └── collectors/              # Per-language detection modules
│       ├── __init__.py
│       ├── python.py
│       ├── javascript.py
│       ├── rust.py
│       └── shell.py
│
├── memory/                      # Memory Engine
│   ├── __init__.py
│   ├── engine.py                # Store, retrieve, index
│   └── store.py                 # SQLite backend
│
├── scheduler/                   # Kanban Engine (v0.8)
│   ├── __init__.py              # Public API exports
│   ├── engine.py                # KanbanEngine (Engine protocol facade)
│   ├── models.py                # KanbanBoard, KanbanCard, KanbanSubtask, KanbanError, COLUMNS
│   └── store.py                 # SQLite backend (kanban_ tables in .aios/memory.db)
│
├── security/                    # Security Manager
│   ├── __init__.py
│   ├── policy.py                # Policy engine, capability evaluation
│   ├── capabilities.py          # Capability grant/revoke
│   ├── secrets.py               # Secret injection, masking
│   ├── firewall.py              # Prompt sanitization
│   └── audit.py                 # Audit trail
│
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── base.py                  # Agent protocol, lifecycle hooks
│   ├── developer.py             # v0.2: single general-purpose agent
│   ├── planner.py               # v0.4: task decomposition
│   ├── coder.py                 # v0.8: specialized coding agent
│   ├── reviewer.py              # v0.5: critique and review
│   ├── tester.py                # v0.6: test execution
│   ├── documentation.py         # v0.6: documentation updates
│   └── git.py                   # v0.7: version control operations
│
├── quality/                     # Quality Pipeline
│   ├── __init__.py
│   ├── pipeline.py              # Orchestrates quality gates
│   └── gates/                   # Individual gate implementations
│       ├── __init__.py
│       ├── format.py
│       ├── lint.py
│       ├── tests.py
│       ├── security_gate.py
│       ├── architecture_review.py
│       └── documentation_review.py
│
├── workflows/                   # Workflow Engine
│   ├── __init__.py
│   ├── engine.py                # Workflow orchestration
│   └── pipelines/               # Predefined workflow definitions
│       ├── __init__.py
│       ├── feature.py
│       ├── fix.py
│       ├── review.py
│       ├── refactor.py
│       ├── document.py
│       └── release.py
│
├── runtime/                     # Runtime Adapter
│   ├── __init__.py
│   ├── base.py                  # Runtime protocol interface
│   └── opencode.py              # OpenCode adapter (via ai-jail)
│
├── plugins/                     # Plugin system
│   ├── __init__.py
│   ├── registry.py              # Plugin discovery and registration
│   └── loader.py                # Dynamic loading
│
├── config/                      # Configuration
│   ├── __init__.py
│   ├── loader.py                # Detect + load + merge config
│   └── schema.py                # Configuration schema definitions
│
└── event_bus/                   # Event infrastructure
    ├── __init__.py
    ├── dispatcher.py            # Topic registry, publish/subscribe
    └── events.py                # Event type definitions
```

### Data Flow — Session Lifecycle

```
1. User runs `aios start`
         │
2. CLI → Kernel → Event: session.start
         │
3. Context Engine detects project
   → Event: context.detected
         │
4. Memory Engine loads prior knowledge
   → Event: memory.loaded
         │
5. Security Manager initializes policies
   → Event: security.ready
         │
6. Runtime Adapter spawns OpenCode via ai-jail
   → Event: runtime.ready
         │
7. Kernel renders status dashboard
   → Event: session.ready
         │
8. User interacts (workflow or ad-hoc)
   → Events flow through system
         │
9. User runs `aios exit` or shutdown
   → Event: session.shutdown
   → Memory Engine persists session data
    → Runtime Adapter terminates
 ```

### Data Flow — `plan --run` via the Workflow Engine

The CLI is thin: it parses arguments, calls the Kernel, and renders the result.
It never talks to agents directly, and it never names an engine.

```
CLI → Kernel.run(task, context, mode, on_stage) → RunResult
        │
        ├── mode="plan"      → PlannerAgent.execute(task, context)
        └── mode="plan-run"  → WorkflowEngine.execute(task, context, on_stage)
                │
                └── Planner → Git(branch) → Scheduler → Developer → Reviewer
                    → Tester → Documentation → Git(commit)
```

The Kernel resolves the right engine internally and normalizes every outcome
into a single `RunResult` (status, stages executed/skipped, artifacts, logs,
errors). The CLI consumes only `RunResult`/`StageSummary` shapes and renders
them. Internal failures are normalized into `RunResult.errors` with a friendly
message — a broken pipeline never escapes as a raw traceback.

The workflow engine owns the orchestration and skips optional stages — tester,
documentation, git — gracefully when the corresponding agent is absent. The
legacy direct-execution path (`AIOS_USE_WORKFLOW_ENGINE`) has been removed:
the workflow is the single source of the pipeline.

### Division of Responsibility Across Ecosystem

```
┌──────────────────────────────────────────────────┐
│                    ProjDesk                       │
│  Physical workspace: folders, IDE, Docker, env    │
│  Output: .aios/project.yaml                      │
├──────────────────────────────────────────────────┤
│                    AiosDeck                       │
│  Intelligence workspace: context, memory, agents  │
│  Consumes: .aios/project.yaml                    │
├──────────────────────────────────────────────────┤
│                    OpenCode                       │
│  Agent runtime: tool execution, skill loading     │
│  Invoked via: ai-jail opencode                   │
├──────────────────────────────────────────────────┤
│                    ai-jail                        │
│  Security: sandbox, policies, filesystem guards   │
│  Invoked by: Runtime Adapter                     │
├──────────────────────────────────────────────────┤
│                    LLM Providers                  │
│  Inference: Ollama, OpenAI, Anthropic, Google     │
│  Invoked by: OpenCode                            │
└──────────────────────────────────────────────────┘
```

### Phase-Based Implementation Strategy

Each phase in the roadmap maps to specific code modules. Documentation drives implementation.

| Phase | Doc | Implementation |
|-------|-----|---------------|
| v0.1 | `phases/phase-01-kernel.md` + `phase-02-context.md` + internals | `core/`, `context/`, `config/`, `event_bus/`, `runtime/`, `security/` (skeleton) |
| v0.2 | `phases/phase-04-agents.md` | `agents/base.py`, `agents/developer.py` |
| v0.3 | `phases/phase-03-memory.md` | `memory/` |
| v0.4 | `agents/planner.md` | `agents/planner.py` |
| v0.5 | `agents/reviewer.md` | `agents/reviewer.py` |
| v0.6 | `agents/planner.md` + Headless SI | `agents/planner.py`, `runtime/opencode.py` (headless hardening) |
| v0.7 | `phases/phase-05-workflows.md` + agent docs | `workflows/`, `agents/git.py` |
| v0.8 | `internals/scheduler.md` (kanban) + `agents/planner.md` | `scheduler/` (kanban engine), kanban integration in `plan --run` |
| v0.9 | `agents/*.md` (remaining) + `phases/phase-05-workflows.md` | `scheduler/` (queue + concurrency), `workflows/`, `plugins/` |
| v1.0 | `phases/phase-06-integrations.md` | `integrations/` adapters |

## Consequences

### Positive

- **Modularity**: Each package is independently testable. No circular dependencies.
- **Gradual implementation**: Each phase adds a package. No rewrite of existing code.
- **Testability**: Event-driven architecture enables isolated testing with mock event buses.
- **Observability**: Centralized event bus makes tracing and debugging straightforward.

### Negative

- **Indirection cost**: Event bus adds latency compared to direct function calls.
- **Protocol overhead**: Every component must adhere to event schemas.
- **Initial complexity**: Building the event bus, context detection, and runtime adapter before the first agent takes discipline.

### Neutral

- The package structure mirrors the documentation structure. A contributor who reads the docs can navigate the code.
- The event-driven model may feel heavy for v0.1–v0.2 when there are few components. The cost pays off at v0.5+ when multiple agents and pipeline stages coordinate.

## Integration Rule

Integrations never expose subprocess or protocol details. They return domain objects or raise domain exceptions. External protocols (CLI exit codes, HTTP, RPC) are translated at the integration boundary.

```
Pattern:

integrations/
├── projdesk/
│   ├── __init__.py
│   ├── client.py        # ProjDeskClient
│   └── exceptions.py    # ProjDeskError → ProjectNotFound, ProjectAmbiguous
├── github/              # (future)
├── docker/              # (future)
└── ollama/              # (future)
```

The rest of the system never sees `CompletedProcess`, `returncode`, `stderr`, or `subprocess.TimeoutExpired`. The integration boundary is the single point where protocol details are translated into the domain language.

## Implementation Notes

- [x] Architecture diagram reflects all components through v1.0
- [x] Package layout defined
- [x] Event schema defined (`event_bus/events.py`)
- [x] Runtime Adapter interface stable — extended with capabilities parameter (v0.6.1)
- [x] Security Manager intercepts events from day one (v0.1 skeleton), event bus logging active
- [ ] Each phase implementation must pass the architecture review gate before being considered done
- [ ] Cross-reference: every `internals/*.md` and `agents/*.md` must link back to this document
