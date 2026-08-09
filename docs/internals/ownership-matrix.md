# Ownership Matrix — AiosDeck v1.0

**Date**: 2026-08-09
**Status**: Accepted

This document defines the ownership boundaries of AiosDeck's core modules.
Each module is owned by a single domain; cross-domain communication happens
through frozen contracts only. No implementation detail leaks across
boundaries.

## Core Domains

| Domain | Module | Responsibility | Owns | Does NOT Own |
|--------|--------|---------------|------|-------------|
| **Workflow** | `src/aios/workflow/` | Orchestration | Pipeline sequencing (planner→developer→reviewer→tester→documentation→git), stage ordering, run identity, health checks | Agent lifecycle, retry, permissions, model selection |
| **Agent Executor** | `src/aios/agents/executor.py` | Lifecycle / Retry / Timeout / Events | Validation, capability enforcement, intent enforcement, timeout, retry loop, cancellation, standardized event publishing (`agent.lifecycle.changed`, `agent.execution.*`) | Prompt building, context assembly, model routing, security decision logic |
| **Security** | `src/aios/security/` | Allow / Deny | `IntentPolicy`, `EffectivePermissions`, `SecurityDecision`, capability→action expansion, safe built-in intents (`DEFAULT_INTENTS`), intent enforcement decisions | Agent lifecycle, event publishing, runtime enforcement (delegated to Agent Executor) |
| **PromptBuilder** | `src/aios/prompts/` | Context Composition | Prompt templates, system/user message assembly | Context layer assembly, knowledge retrieval, skill injection |
| **ContextAssembler** | `src/aios/context/` | Context Composition | Layer assembly (`Layer`, `LayeredContext`), dedup, ordering, truncation, `ContextPacket` | Prompt rendering, knowledge indexing, memory persistence |
| **CLI** | `src/aios/cli/` | Presentation | Argument parsing, command dispatch, output rendering (TUI + console), user-facing error messages | Business logic, agent execution, security decisions |
| **Kernel** | `src/aios/core/kernel.py` | Bootstrap / Dispatch | Engine startup order (`INIT_ORDER`), engine lifecycle (initialize→health_check→shutdown), top-level `run()` dispatch, `Engine` protocol | Domain-specific logic — delegates to engines |
| **Core** | `src/aios/core/` | Standardized Output | `RunResult`, `StageSummary` — the CLI-consumed contract that normalizes any execution (single agent, full workflow, future engine) | Execution mechanics, pipeline decisions |
| **Learning** | `src/aios/learning/` | Governance | `LearningEngine` — observation→extraction→governance→ingestion pipeline, `LearningAdvisor` for candidate review | Direct knowledge mutation, bypassing review |
| **Knowledge** | `src/aios/knowledge/` | Retrieval | `KnowledgeEngine` — indexing, chunking, querying, deduplication | Learning governance, memory orchestration |
| **Memory** | `src/aios/memory/` | Persistence | `MemoryEngine` — project-level knowledge persistence (`ProjectKnowledge`), session-scoped state | Learning lifecycle, knowledge indexing |
| **Telemetry** | `src/aios/telemetry/` | Observation | `TelemetryEngine` — execution recording, token tracking, cost calculation, `PricingResolver` | Decision-making (observes only, never routes) |
| **Routing** | `src/aios/routing/` | Model Selection | `RuleBasedRouter`, route decisions, fallback chains, cost caps | Agent lifecycle, execution mechanics — consumed by `RuntimeEngine` |
| **Skills** | `src/aios/skills/` | Toolbox | `SkillRegistry`, `SkillAssembler`, discovery, retrieval, skill metadata | Agent execution, prompt building |
| **Quality** | `src/aios/quality/` | Gates | `QualityGate` protocol, gate vocabulary (`GateFinding`, `GateResult`, `GateDecision`), severity mapping | Agent execution, pipeline sequencing — invoked by workflow |
| **Events** | `src/aios/events/` | Bus | `EventBus`, topic vocabulary (`ALL_TOPICS`), subscription, publishing | Domain logic — is a pipe, not a domain |

## Boundary Rules

1. **Agents are executor-free.** No agent imports `AgentExecutor`. The executor is the only component that invokes `agent.execute()`.
2. **Security decides; the executor enforces.** `SecurityDecision` is computed by `aios.security`; the executor reads it and publishes audit events.
3. **Workflow orchestrates; it does not execute.** The workflow engine calls `AgentExecutor.execute()` for every agent run. It never calls `agent.execute()` directly.
4. **CLI presents; it never executes.** The CLI converts user input into kernel calls and renders output. It owns no business logic.
5. **Kernel bootstraps; engines own their logic.** The kernel starts all engines in `INIT_ORDER` and delegates `run()` to the appropriate engine.

## Post-1.0 Labels

The following features are explicitly labeled as post-1.0 and MUST NOT be implemented
in the v1.0 stabilization:

- **TelemetryRanker** — data-driven model ranking (post-1.0). Current `HeuristicRanker` is the stable ranker.
- **Auto-optimization** — automatic parameter tuning from telemetry feedback (post-1.0).
- **Advanced widgets** — complex TUI widgets beyond the ocean overview (post-1.0).
- **Plugin system** — dynamic extension loading (post-1.0).
- **Concurrent queue** — parallel agent execution (post-1.0).
- **Learning auto-ingestion** — bypassing the governance review (post-1.0).

## Contract Freeze

The following contracts are frozen for v1.0 and MUST NOT change their public
signatures without a version bump:

| Contract | File | Frozen Fields |
|----------|------|---------------|
| `AgentTask` | `src/aios/agents/contracts.py:88` | `description`, `task_type`, `files`, `params`, `task_id`, `correlation_id` |
| `AgentResult` | `src/aios/agents/models.py:59` | `success`, `output`, `errors`, `error`, `error_code`, `duration_ms`, `status` |
| `ExecutionRequest` | `src/aios/agents/models.py:29` | `agent`, `task`, `context`, `timeout`, `retry_policy`, `correlation_id`, `intent` |
| `ExecutionOutcome` | `src/aios/agents/models.py:43` | `status`, `result`, `error`, `duration_ms`, `attempts`, `retried` |
| `RunResult` | `src/aios/core/run_result.py:27` | `success`, `stages`, `errors`, `output`, `plan`, `subtask_count`, `completed_count` |
| `StageSummary` | `src/aios/core/run_result.py:17` | `name`, `status`, `reason`, `details` |
| `IntentPolicy` | `src/aios/security/contracts.py:25` | `actions` (frozenset), `deny` (frozenset), `name`, `source` |
| `EffectivePermissions` | `src/aios/security/contracts.py:48` | `allowed` (frozenset) |
| `SecurityDecision` | `src/aios/security/contracts.py:63` | `action`, `allowed`, `reason`, `violations`, `effective_permissions` |
| `AgentError` | `src/aios/agents/contracts.py:140` | `code`, `message`, `transient` |
