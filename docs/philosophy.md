# Philosophy

**Status**: Implemented — the ten principles actively govern the codebase and
every stabilized decision in v1.0.
**Date**: 2026-08-02

## Context

AiosDeck inherits its philosophy from ProjDesk — a workspace manager built on the principle that tools should adapt to the developer, not the other way around. ProjDesk proved that detection, automation, and minimal configuration produce tools that developers actually use. AiosDeck extends this philosophy from the physical workspace to the intelligence workspace.

Every architectural decision in AiosDeck must pass through these principles. If a decision violates a principle, either the decision is wrong or the principle needs revision. These principles are the project's **DNA**.

## Decision

AiosDeck is guided by ten core principles and three sub-principles. Each principle is a constraint, not a suggestion.

### 1. Context before Intelligence

Better context produces better answers. A language model with perfect context outperforms a smarter model with no context.

AiosDeck injects project-specific knowledge **before every prompt**: language, framework, conventions, architecture, dependencies, recent changes, related files, and project history. The model's job is to reason — the system's job is to provide the reasoning material.

**What this means in practice**: The Context Engine runs before any agent prompt. It is not optional. It is the first stage of every workflow.

### 2. Automation over Prompts

Detect whenever possible. Never ask what can be discovered.

If the project language can be detected from `pyproject.toml`, do not ask "What language is this?" If the test framework can be inferred from `pytest.ini`, do not ask "What test runner do you use?" If Git is present, detect the branch and status — do not ask for them.

**What this means in practice**: The detection layer runs at session start and feeds the Context Engine. Configuration files exist only for what cannot be detected.

### 3. One Agent. One Responsibility.

Every agent has exactly one job. Nothing more. Nothing less.

This is the same principle that makes Unix tools composable: `grep` finds text, `sort` orders lines, `wc` counts them. No tool does more than its name suggests. AiosDeck agents follow the same rule.

| Agent | One Job |
|-------|---------|
| Planner | Decompose tasks |
| Developer | Write code |
| Reviewer | Critique output |
| Tester | Verify behavior |
| Git | Manage version control |

**What this means in practice**: Agents never share logic. When an agent's responsibilities grow, **split the agent**, do not expand it. The first agent (Developer, v0.2) is the only exception — and it exists only until its responsibilities are ready to be split.

Infrastructure shared by multiple agents (timeout, metrics, Event Bus publishing) lives in the **AgentExecutor** (v0.5). This is not a violation of the principle — it is the execution guardrail, not the agent's domain logic. The Executor does not know what it executes; agents do not know how they are executed.

### 4. Events over Function Calls

Communication between system components happens through an event bus, never through direct function calls or imports.

When the Planner creates a task, it emits a `task.created` event. The Scheduler picks it up. When the Developer completes work, it emits `code.written`. The Reviewer subscribes. No module imports another module's internals. The bus is the backbone — everything else plugs into it.

**What this means in practice**: Every module exposes two interfaces: the events it emits and the events it consumes. Internal implementation is invisible to the rest of the system.

### 5. Humans Own the Architecture

Humans define goals. Agents execute. Architecture decisions — what the system should look like, which patterns to follow, which trade-offs to make — are human territory.

Agents implement within constraints. They do not redesign the system. They do not choose between microservices and monoliths. They do not decide to rewrite the frontend in a new framework. The human owns the architecture; the agents own the implementation.

**What this means in practice**: Approval Gates block any agent action that would change system architecture. `git push`, `docker rm`, database migrations — all require human confirmation.

### 6. Local First. Cloud Optional.

Everything runs locally by default. Cloud models are an option, never a requirement.

- Context assembly: local filesystem
- Memory persistence: local SQLite
- Runtime execution: local process (via ai-jail)
- LLM inference: local model (via Ollama) by default, cloud models as fallback

**What this means in practice**: The system must work without internet access. Cloud integrations are adapters, not core dependencies. The Runtime Adapter defaults to local, switches to cloud only when explicitly configured.

### 7. Memory Is a First-Class Citizen

Memory is not a cache. It is not a configuration file. It is a core system component with its own engine, schema, and lifecycle.

The Memory Engine stores: conventions discovered from the codebase, decisions documented in ADRs, architectural patterns identified by reviewers, common mistakes that agents should avoid, and context that survives across sessions. Memory grows alongside the project — every interaction enriches it.

**What this means in practice**: No agent stores state internally. All persistent knowledge flows through the Memory Engine. The system can be restarted without losing what it learned.

### 8. The Runtime Is Replaceable

OpenCode is one runtime. Not **the** runtime.

The Runtime Adapter abstracts the execution environment behind a stable interface. Today the adapter speaks to OpenCode. Tomorrow it could speak to a different agent runtime. The adapter pattern ensures that the rest of the system — kernel, agents, memory, scheduler — is decoupled from any specific runtime.

**What this means in practice**: The Runtime Adapter is an interface with a single implementation today. Every protocol-level concern (authentication, tool calling, skill loading) is handled by the adapter, not by agents directly.

### 9. Security Is Architecture, Not a Feature

Security is not a module you add later. It is embedded in the kernel, the runtime, the agent model, the event bus — in every component.

- **Zero-trust**: Every agent is untrusted until explicitly authorized.
- **Capabilities**: Agents receive the minimum permissions required — never blanket access.
- **Defense in depth**: Multiple layers (Policy Engine, ai-jail sandbox, filesystem guards, Approval Gates) protect the system.
- **Audit trail**: Every action is logged with timestamp, agent, and outcome.

**What this means in practice**: Security is enforced at the architecture level, not the prompt level. No amount of "please be safe" in a system prompt replaces a capability-based permission system.

### 10. The ProjDesk Contract

ProjDesk manages the development environment. AiosDeck manages the intelligence environment. This boundary is the project's identity — and its guard-rail against scope creep.

If a proposed feature does not help manage the developer's intelligence workspace (context, planning, implementation, review, documentation, memory, workflows), it does not belong in AiosDeck. It is either ProjDesk's responsibility or a separate tool entirely.

**What this means in practice**: Every new feature request is tested against the question: "Does this help manage the intelligence environment?" Secrets management for CI/CD pipelines? No — that's environment management. Docker container lifecycle? No — that's ProjDesk. Coordinating which agent reviews which code change? Yes — that's intelligence orchestration.

### Sub-Principles

#### Composable Everything

Every component is designed to be replaced, extended, or composed. Runtimes, agents, workflows, skills, quality gates — all are pluggable. The system ships with defaults, not with hard-coded choices.

#### AI Is Replaceable

The language model behind any agent can be swapped without changing the agent's behavior contract. A Planner using GPT-4 and a Planner using Claude follow the same interface. The model is an implementation detail.

#### The Invisible Assistant

When AiosDeck works correctly, the developer should not feel its presence. Silent success, loud failure. The system runs quality checks, loads context, schedules tasks — all without prompting the developer. The developer only interacts when a decision requires human judgment.

### Meta-Principle

> **Every abstraction must solve an existing problem. Never an anticipated one.**

This principle constrains all others. If a proposed component (agent, engine, pipeline stage) does not solve a problem that already exists in the current codebase, it is deferred. The architecture documents the vision; the implementation ships only what is needed today.

## Consequences

### Positive

- **Coherence**: Every component aligns with the same principles, making the system predictable and maintainable.
- **Simplicity**: Constraints force minimalism. The system grows in capability without growing in complexity.
- **Trust**: Security-by-design and the meta-principle of solving only real problems build user confidence.
- **Adoptability**: Local-first makes the tool accessible. Runtime-agnostic prevents vendor lock-in.

### Negative

- **Slower initial development**: Building detection, context assembly, and security boundaries takes more time than a simple prompt wrapper.
- **Constraint tension**: Principles can conflict (e.g., "Automation over Prompts" vs. "Humans Own the Architecture" for ambiguous situations).
- **Documentation burden**: Every component must justify itself against the principles in its ADR.

### Neutral

- Principles evolve. When a principle no longer serves the project, it is revised — not ignored.
- The philosophy applies to the AiosDeck project itself. The codebase must follow its own principles.

## Implementation Notes

- [ ] Every ADR document must include a "Philosophy Alignment" section referencing which principles it supports
- [ ] Principles 1–10 should be visible in the README, linked here for detail
- [ ] The meta-principle must be enforced in code review: no feature ships without an existing problem to solve
- [ ] Principle conflicts should be documented as they arise; update this document when resolution patterns emerge
