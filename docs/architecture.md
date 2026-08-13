# Architecture

**Status**: Implemented — the hub-and-spoke architecture (Kernel + engines) is
the shipping design of v1.0.
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
             Planner        Developer           Reviewer
               │                │                  │
               │  (loads Skills via the active     │
               │   runtime's native skill mechanism│
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
| **AgentExecutor** | Single execution boundary. Validates the AgentTask, enforces capabilities, drives the lifecycle, applies timeout/retry/cancellation centrally, and publishes the `agent.*` lifecycle events. Invokes `agent.execute()` — agents are executor-free. | Consumer + Producer | v0.5 (v0.9.2 hardening) |
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
                             ├── agent.lifecycle.changed
                             ├── agent.execution.started
                             ├── agent.execution.progress
                             ├── agent.execution.completed
                             ├── agent.execution.failed
                             ├── agent.execution.timed_out
                             ├── agent.execution.retried
                             ├── agent.execution.cancelled
                             ├── quality.passed
                            ├── quality.failed
                            ├── security.violation
                            ├── approval.requested
                            └── audit.logged
```

Events are fire-and-forget. Producers do not know consumers. Consumers do not know producers. The dispatcher is the only component that knows all routes.

### Python Package Layout

```
aios/
├── __init__.py
├── __main__.py                  # python -m aios
├── tools.py                     # Shared tooling helpers
│
├── core/                        # Kernel + CLI
│   ├── __init__.py
│   ├── kernel.py                # Bootstrap, lifecycle, dispatcher
│   ├── engine.py                # Engine protocol
│   ├── console.py               # Dashboard rendering
│   ├── run_result.py            # RunResult / StageSummary normalization
│   └── task.py                  # Task dataclass
│
├── cli/                         # CLI surface (v0.6.1)
│   ├── __init__.py
│   ├── main.py                  # Thin dispatcher — reads COMMANDS, resolves aliases
│   ├── completion.py            # Autocomplete engine consuming registry
│   └── commands/                # Command registry (package)
│       ├── __init__.py
│       ├── core.py              # core commands
│       ├── exec_cmds.py         # execution commands
│       └── memory.py            # memory commands
│
├── events/                      # Event infrastructure
│   ├── __init__.py
│   ├── bus.py                   # EventBus: topic registry, publish/subscribe
│   └── events.py                # Event type definitions
│
├── config/                      # Configuration
│   ├── __init__.py
│   ├── loader.py                # Detect + load + merge config
│   └── schema.py                # Configuration schema definitions
│
├── context/                     # Context Engine
│   ├── __init__.py
│   ├── assembler.py             # Assembles context layers
│   ├── assembly.py              # Context assembly pipeline
│   ├── detector.py              # Project detection
│   ├── layers.py                # Context layer definitions
│   ├── packet.py                # ContextPacket
│   ├── cli.py                   # context CLI commands
│   └── collectors/              # Per-language detection modules
│       ├── __init__.py
│       ├── python.py
│       ├── javascript.py
│       └── shell.py
│
├── memory/                      # Memory Engine
│   ├── __init__.py
│   ├── engine.py                # Store, retrieve, index
│   ├── models.py                # Memory dataclasses
│   └── store.py                 # SQLite backend
│
├── scheduler/                   # Kanban Engine (v0.8)
│   ├── __init__.py              # Public API exports
│   ├── engine.py                # KanbanEngine (Engine protocol facade)
│   ├── models.py                # KanbanBoard, KanbanCard, KanbanSubtask, KanbanError, COLUMNS
│   ├── store.py                 # SQLite backend (kanban_ tables in .aios/memory.db)
│   └── backlog_writer.py        # TODO.md backlog writer
│
├── security/                    # Security Manager
│   ├── __init__.py
│   ├── contracts.py             # Security contracts
│   ├── intent_validator.py      # Zero-trust intent validation
│   ├── resolver.py              # Policy/capability resolution
│   ├── capabilities.py          # Capability grant/revoke
│   ├── actions.py               # Action definitions
│   └── cli.py                   # security CLI commands
│
├── agents/                      # Agent implementations
│   ├── __init__.py
│   ├── base.py                  # Agent protocol, lifecycle hooks
│   ├── contracts.py             # AgentTask, AgentResult, AgentError, capabilities
│   ├── executor.py              # AgentExecutor — the single execution boundary
│   ├── lifecycle.py             # AgentLifecycle state machine
│   ├── models.py                # Agent dataclasses
│   ├── detectors.py             # Agent detection
│   ├── developer.py             # v0.2: implementation agent
│   ├── planner.py               # v0.4: task decomposition
│   ├── reviewer.py              # v0.5: critique and review
│   ├── tester.py                # v0.6: test execution
│   ├── documentation.py         # v0.6: documentation updates
│   ├── git.py                   # v0.7: version control operations
│   └── research.py              # v0.9: research agent
│
├── quality/                     # Quality Pipeline
│   ├── __init__.py
│   ├── contracts.py             # Quality contracts
│   ├── policy.py                # Quality policy
│   ├── cli.py                   # quality CLI commands
│   └── gates/                   # Individual gate implementations
│       ├── __init__.py
│       ├── common.py
│       ├── code.py
│       ├── documentation.py
│       ├── release.py
│       ├── security.py
│       └── tester.py
│
├── workflow/                    # Workflow Engine
│   ├── __init__.py
│   ├── engine.py                # Workflow orchestration
│   └── models.py                # Workflow dataclasses
│
├── runtime/                     # Runtime Adapter
│   ├── __init__.py
│   ├── base.py                  # Runtime protocol interface
│   └── opencode.py              # OpenCode adapter (via ai-jail)
│
├── backlog/                     # Backlog processing
│   ├── __init__.py
│   ├── cli.py                   # backlog CLI commands
│   ├── models.py                # Backlog models
│   ├── parser.py                # Backlog parsing
│   └── runner.py                # Backlog execution runner
│
├── learning/                    # Learning governance
│   ├── __init__.py
│   ├── engine.py                # Learning engine (approval-gated)
│   ├── contracts.py             # Learning contracts
│   ├── extractor.py             # Observation extraction
│   ├── advisor.py               # RulesAdvisor (deterministic)
│   ├── models.py                # Learning dataclasses
│   ├── store.py                 # Learning store
│   └── cli.py                   # learning CLI commands
│
├── knowledge/                   # Knowledge Engine
│   ├── __init__.py
│   ├── engine.py                # Knowledge engine
│   ├── chunking.py              # Text chunking
│   ├── discovery.py             # Knowledge discovery
│   ├── models.py                # Knowledge dataclasses
│   ├── store.py                 # Knowledge store
│   └── cli.py                   # knowledge CLI commands
│
├── retrieval/                   # Retrieval
│   ├── __init__.py
│   ├── retrievers.py            # Retrieval strategies
│   ├── providers.py             # Provider adapters
│   └── selector.py              # Retriever selection
│
├── routing/                     # Model routing
│   ├── __init__.py
│   ├── engine.py                # RuleBasedRouter
│   ├── models.py                # Routing dataclasses
│   ├── contracts.py             # ModelRanker protocol (stub, post-1.0)
│   └── cli.py                   # route CLI commands
│
├── skills/                      # Skills subsystem
│   ├── __init__.py
│   ├── registry.py              # Skill registry
│   ├── discovery.py             # Skill discovery
│   ├── metadata.py              # Skill metadata
│   ├── retrieval.py             # Skill retrieval
│   ├── assembler.py             # Skill assembly
│   ├── telemetry.py             # Skill telemetry
│   └── cli.py                   # skills CLI commands
│
├── telemetry/                   # Telemetry
│   ├── __init__.py
│   ├── engine.py                # Telemetry engine (subscribes, builds records)
│   ├── writer.py                # Buffered async batch writer
│   ├── pricing.py               # Cost tracking
│   ├── store.py                 # Telemetry store (schema, SQL, queries)
│   └── cli.py                   # telemetry CLI commands
│
├── usage/                       # Usage records
│   ├── __init__.py
│   └── models.py                # Usage dataclasses
│
├── prompts/                     # Prompt building
│   ├── __init__.py
│   ├── builder.py               # Prompt builder
│   └── layered.py               # Layered prompts
│
├── research/                    # Research
│   ├── __init__.py
│   ├── models.py                # Research dataclasses
│   └── schema.py                # Research schema
│
├── ui/                          # Terminal UI (ocean dashboard)
│   ├── __init__.py
│   ├── cli.py                   # ui CLI commands
│   ├── components.py            # UI components
│   ├── datasources.py           # Dashboard data sources
│   ├── mode.py                  # UI modes
│   ├── pages.py                 # Dashboard pages
│   ├── render.py                # Rendering helpers
│   ├── resolver.py              # Resolution helpers
│   ├── settings_io.py           # Settings persistence
│   ├── settings_page.py         # Settings page
│   ├── theme.py                 # Semantic design tokens
│   └── tui.py                   # TUI renderer
│
├── storage/                     # Thread-safe storage helpers
│   ├── __init__.py
│   └── threadsafe.py            # Thread-safe containers
│
└── integrations/                # External integrations
    ├── __init__.py
    └── projdesk/                # ProjDesk client
        ├── __init__.py
        ├── client.py            # ProjDeskClient
        └── exceptions.py        # ProjDeskError → ProjectNotFound, ProjectAmbiguous
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

### Execution Boundary (v0.9.2)

The **AgentExecutor is the single execution boundary**. It orchestrates every
agent run and invokes `agent.execute(task, context)` — the agent's contract
method. Agents are executor-free: they never hold or call the executor, so
recursion is structurally impossible.

```
Kernel / Workflow / CLI
        │
        ▼
    AgentExecutor           ← the only entry to agent execution
        │
   ┌────┼───────┬───────────┐
 validate  capability  lifecycle/timeout/retry/events
        │
        ▼
  agent.execute(task, context)   ← contract method (pure domain)
        │
        ▼
  agent._run()/_review()/...     ← internal implementation / runtime adapter
```

Lifecycle: `created → validated → queued → running → succeeded | failed | timed_out | cancelled`
(running → running is a retry). Every transition emits `agent.lifecycle.changed`;
execution observability emits `agent.execution.*`. The `created → created`
event is the initialization event, not a transition — it guarantees every
execution has a complete, deterministic sequence.

Invariants enforced by the architecture test suite:

1. `Agent → AgentExecutor`: impossible (no agent module imports the executor).
2. `Workflow/CLI → rich domain APIs`: forbidden — they route via `execute()` /
   `Kernel.run_agent()`.
3. `Runtime → outside the adapter`: forbidden — the runtime is reached only
   through the runtime adapter, inside `agent.execute()`.
4. `agent.lifecycle.*` / `agent.execution.*` events: only `AgentExecutor`
   publishes them.
5. The legacy `agent.execution.finished` vocabulary is removed.

### v1.0 Labeling — What Ships, What Is Deferred

v1.0 is a **stabilization release**: contracts frozen, security closed, dead
code removed. The following labeling documents what is in the v1.0 core and
what is explicitly deferred. This is documentation, not code — nothing here is
guarded by a feature flag.

#### v1.0 Core

- **Learning governance** — the approval-gated pipeline: observation →
  extraction → human review → ingestion. Deterministic `RulesAdvisor`;
  no automatic ingestion without review.
- **`RuleBasedRouter`** — deterministic, policy-driven model routing
  (`policy:<index>` | `heuristic:default` | `explicit_override`). No
  telemetry-driven ranking in v1.0.
- **Basic console** — `aios ocean` overview with semantic design tokens, and
  the standard CLI (help, completion, doctor, plan, review, research, memory,
  knowledge, skills, learning, security, policy, quality, route, usage,
  backlog).

#### Beta-flag / Deferred (post-1.0)

- **Auto-optimization** — automatic learning-ingestion without human review.
- **TelemetryRanker** — data-driven model ranking. Removed in v1.0; the
  `ModelRanker` protocol remains in `routing/contracts.py` as a stub contract.
- **Advanced widgets / forms** — complex TUI widgets beyond the ocean overview.
- **Plugin system** — dynamic extension loading.
- **Concurrent execution queue** — parallel agent dispatch.
- **Desktop / web integrations** — ProjDesk remains the only integration.
- **Real cost tracking** — `route_accuracy` via parsing opencode
  `--format json` output.

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

### Skill Contract

Skills are an AiosDeck abstraction for modular knowledge, not a runtime feature. The contract between agents and runtimes:

```
Agent ──► Skill Contract ──► Runtime Adapter ──► Runtime
   │              │                 │               │
   │ declares     │ resolved by     │ maps Skill    │ native
   │ required_    │ manifest +      │ into runtime  │ context
   │ skills       │ agent config    │ mechanism     │ loading
```

Contract rules:

1. **Agents never load Skills directly.** They declare `required_skills` in the manifest or agent configuration.
2. **The Runtime Adapter resolves every Skill** against the active runtime's native context-loading mechanism before each task.
3. **Runtimes may implement Skills differently.** The OpenCode adapter maps Skills to its skill tool (`SKILL.md` discovery). A future adapter maps them through a different mechanism — no agent code changes.
4. **Core Skills shipped by AiosDeck are runtime-agnostic** markdown knowledge fragments. Runtime-specific behavior lives in the adapter, not in the Skill content.

> **TODO (technical)**: Define a `SkillResolver` interface in `runtime/base.py` so future adapters implement `resolve(skill) -> runtime-native handle` without touching agents or the manifest.

### Phase-Based Implementation Strategy

Each phase in the roadmap maps to specific code modules. Documentation drives implementation.

| Phase | Doc | Implementation |
|-------|-----|---------------|
| v0.1 | `phases/phase-01-kernel.md` + `phase-02-context.md` + internals | `core/`, `context/`, `config/`, `events/`, `runtime/`, `security/` (skeleton) |
| v0.2 | `phases/phase-04-agents.md` | `agents/base.py`, `agents/developer.py` |
| v0.3 | `phases/phase-03-memory.md` | `memory/` |
| v0.4 | `agents/planner.md` | `agents/planner.py` |
| v0.5 | `agents/reviewer.md` | `agents/reviewer.py` |
| v0.6 | `agents/planner.md` + Headless SI | `agents/planner.py`, `runtime/opencode.py` (headless hardening) |
| v0.7 | `phases/phase-05-workflows.md` + agent docs | `workflow/`, `agents/git.py` |
| v0.8 | `internals/scheduler.md` (kanban) + `agents/planner.md` | `scheduler/` (kanban engine), kanban integration in `plan --run` |
| v0.9 | `agents/*.md` (remaining) + `phases/phase-05-workflows.md` | `scheduler/` (queue + concurrency), `workflow/`, `skills/`, `telemetry/`, `routing/` |
| v1.0 | `phases/phase-06-integrations.md` | `integrations/projdesk/`, `backlog/`, `learning/`, `knowledge/`, `retrieval/`, `ui/`, `storage/` |

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
- [x] Event schema defined (`events/events.py`, `events/bus.py`)
- [x] Runtime Adapter interface stable — extended with capabilities parameter (v0.6.1)
- [x] Security Manager intercepts events from day one (v0.1 skeleton), event bus logging active
- [ ] Each phase implementation must pass the architecture review gate before being considered done
- [ ] Cross-reference: every `internals/*.md` and `agents/*.md` must link back to this document
