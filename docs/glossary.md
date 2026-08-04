# Glossary

**Status**: Accepted (incremental — updated with each new document)
**Date**: 2026-08-02

## Context

AiosDeck introduces specific terminology that must be used consistently across all documentation and code. This glossary serves as the authoritative reference. Terms are added incrementally as they are introduced in architecture documents, agent specifications, and implementation notes.

## Core Concepts

### Agent

A specialized worker process with a single responsibility. Agents receive tasks via the Scheduler, execute them through the Runtime Adapter, and emit results as events. Every agent has: an `In → Process → Out` contract, a list of events it consumes, a list of events it emits, a set of capabilities it requires, and a version number indicating when it was introduced.

**First used in**: `agents/` documentation. **Introduced**: v0.2.

### AgentExecutor

The execution guardrail shared by all LLM-based agents. Receives an `ExecutionRequest` (a callable operation), enforces timeout and retry (future), publishes `agent.execution.*` events to the Event Bus, and returns a neutral `ExecutionOutcome`. The Executor does not know about agents, prompts, LLMs, or runtimes — it only executes operations.

**First used in**: `agents/executor.py`. **Introduced**: v0.5.

### ExecutionRequest

A value object carrying the operation to execute. Contains a single field: `invoke` — a callable that returns a string. The AgentExecutor calls `request.invoke()` without knowing what the operation does (LLM prompt, Git command, HTTP call, etc.).

**First used in**: `agents/models.py`. **Introduced**: v0.5.

### ExecutionOutcome

The neutral result returned by `AgentExecutor`. Contains `output` (string), `duration_ms` (float), and optional `error`. The Executor never decides success vs. failure — it reports facts. The agent interprets the outcome into an `AgentResult`.

**First used in**: `agents/models.py`. **Introduced**: v0.5.

### ProjDeskClient

The domain client for ProjDesk integration. Wraps the `pd` CLI behind `resolve(name) -> Path`. Translates exit codes (0/1/2) into domain exceptions (`ProjectNotFound`, `ProjectAmbiguous`, `ProjDeskError`). Never exposes subprocess, returncode, or stderr to the rest of the system.

**First used in**: `integrations/projdesk/client.py`. **Introduced**: v0.5.

### Runtime

The execution environment that runs an agent and communicates with a language model. The Runtime Adapter abstracts the specific implementation behind a stable interface. OpenCode is the primary runtime. Future runtimes could include direct LLM API calls or other agent frameworks.

**First used in**: `internals/runtime.md`. **Introduced**: v0.1.

### Context

All information about a project that an agent needs to produce high-quality output: language, framework, conventions, architecture patterns, dependencies, recent changes, related files, project history. The Context Engine detects project characteristics automatically and assembles this context before every agent prompt.

**First used in**: `phases/phase-02-context.md`. **Introduced**: v0.1.

### Memory

Persistent knowledge that survives across sessions. The Memory Engine stores conventions, decisions (ADRs), architectural patterns, common mistakes, and session history in SQLite. Unlike context (which is detected fresh each session), memory accumulates over time.

**First used in**: `phases/phase-03-memory.md`. **Introduced**: v0.3.

### Workflow

A predefined sequence of agent actions and quality gates that accomplishes a specific goal. Workflows are invoked through semantic commands: `/feature`, `/fix`, `/review`, `/refactor`, `/document`, `/release`. Each workflow defines which agents run, in what order, and which quality gates apply.

**First used in**: `phases/phase-05-workflows.md`. **Introduced**: v0.7.

### Scheduler

The component that manages the task queue. It receives tasks from the Kernel or Workflow Engine, prioritizes them, and dispatches them to available agents. The Scheduler supports concurrency (multiple agents running in parallel) starting in v0.8.

**First used in**: `internals/scheduler.md`. **Introduced**: v0.8 (basic queue from v0.1).

### Kernel

The central coordinator of the AiosDeck system. It handles bootstrap (loading configuration, initializing engines), lifecycle (starting, running, shutting down), and event dispatch (routing events between components). The Kernel is the hub; everything else is a spoke.

**First used in**: `phases/phase-01-kernel.md`. **Introduced**: v0.1.

### Plugin

An extension that adds capability to an existing extension point. Plugins can add new Runtimes, Agents, Skills, Workflows, or Quality Gates. The Plugin System handles discovery, registration, and loading. AiosDeck ships with core plugins; third-party plugins are supported from v0.9.

**First used in**: `internals/plugin-system.md`. **Introduced**: v0.9.

### Workspace

The physical directory containing a project. Managed by ProjDesk. AiosDeck operates within a workspace but does not create or manage it. The workspace contains the `aios/project.yaml` manifest that AiosDeck reads.

**First used in**: `integrations/projdesk.md`. **Introduced**: v0.1 (via ProjDesk integration).

### Task

A unit of work assigned to an agent. Tasks have a description, type (code, fix, feature, review, document, refactor, release), and optional file list. Tasks flow through the Scheduler, which dispatches them to appropriate agents. Lives in `aios.core.task`.

**First used in**: `internals/scheduler.md`. **Introduced**: v0.1.

### Event

A structured message published to the Event Bus. Events have a topic, payload, timestamp, and optional correlation ID. Components communicate exclusively through events. The Event Bus is the backbone of the system.

**First used in**: `internals/event-bus.md`. **Introduced**: v0.1.

### Event Bus

The pub/sub infrastructure that routes messages between components. Topics are hierarchical (e.g., `task.created`, `agent.completed`). The Event Dispatcher manages topic registration, subscription, and delivery. No component communicates directly with another.

**First used in**: `internals/event-bus.md`. **Introduced**: v0.1.

### Skill

A reusable knowledge fragment loaded by OpenCode's native skill tool. Skills teach agents how to work with specific technologies, patterns, or conventions. AiosDeck ships core Skills; project-specific Skills live in `.opencode/skills/`.

**First used in**: `agents/` documentation. **Introduced**: v0.1 (via OpenCode).

### Capability

A permission granted to an agent. Capabilities are fine-grained: `filesystem:read`, `filesystem:write`, `internet`, `git`, `shell`, `docker`. The Capability Manager assigns capabilities at agent startup based on policies. No agent receives blanket access.

**First used in**: `internals/security.md`. **Introduced**: v0.1 (policy skeleton), v0.6 (full enforcement).

### Quality Gate

An automated check in the Quality Pipeline. Gates execute in order: Format, Lint, Tests, Security, AI Architecture Review, Documentation Review. If a gate fails, the task returns to the agent for correction. Gates are detected automatically based on project type.

**First used in**: `internals/quality-pipeline.md`. **Introduced**: v0.6.

### Project Manifest

A YAML file (`aios/project.yaml`) that describes how a project should be understood by AiosDeck. It declares: language, runtime, quality tools, active skills, and available workflows. ProjDesk can generate it. AiosDeck consumes it.

**First used in**: `integrations/projdesk.md`. **Introduced**: v0.1.

### Approval Gate

A mandatory human confirmation step for destructive operations. Actions like `git push`, `docker rm`, database migrations, and directory deletions require explicit approval before execution. The Approval Gate component intercepts these actions and prompts the developer.

**First used in**: `internals/security.md`. **Introduced**: v0.6.

### Policy

A YAML configuration that defines which capabilities each agent receives. Policies can be per-project (`aios/policies/default.yaml`), per-agent, or per-environment. The Policy Engine evaluates policies at agent startup.

**First used in**: `internals/security.md`. **Introduced**: v0.1 (skeleton), v0.6 (full enforcement).

### Command Registry

The single source of truth for CLI commands, help output, and autocomplete suggestions. Defined in `cli/commands.py` as `COMMANDS: dict[str, Command]`. Each `Command` has `name`, `description`, `aliases`, `subcommands`, `execute`, and `hidden`. Adding a command requires one entry — the parser, help system, and autocomplete all consume the same registry. The thin dispatcher in `cli/main.py` resolves command names and aliases against COMMANDS.

**First used in**: `cli-philosophy.md`. **Introduced**: v0.6.1.

### OpenCode Permission

A runtime-level tool permission injected by the Runtime Adapter via the `OPENCODE_PERMISSION` environment variable. Used in headless mode to prevent tools that require human interaction (e.g., `question`) from causing silent subprocess timeouts. Permissions are binary (`allow`/`deny`) and derived from agent capabilities: PlannerAgent gets `edit: deny, bash: deny`; DeveloperAgent only gets `question: deny`.

**First used in**: `integrations/opencode.md`. **Introduced**: v0.6.1.

---

*Terms are added to this glossary incrementally. Each new document that introduces a concept must submit a glossary entry.*
