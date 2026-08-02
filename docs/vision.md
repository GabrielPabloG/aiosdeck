# Vision

**Status**: Accepted
**Date**: 2026-08-02

## Context

AI-assisted development is fragmented. Developers interact with language models through isolated chat interfaces — OpenAI's ChatGPT, Anthropic's Claude, Google's Gemini, or local models via Ollama. Each conversation is stateless. Each tool reinvents context management. The model is always the center of the interaction, and the developer is always the bottleneck.

Meanwhile, tools like Claude Code, Aider, Cursor, and OpenCode have advanced the state of AI coding agents — but they remain **single-model, single-session** tools. They excel at answering questions and generating code snippets, but they lack memory, coordination, security boundaries, and workflow awareness.

The next frontier is not a better model. It is a better **orchestration layer**.

## Decision

AiosDeck is an **AI operating system for developers** — an orchestration platform that manages multiple specialized AI agents as a coordinated team, not as isolated conversations.

Just as an operating system abstracts hardware (CPU, memory, disk) and provides processes, scheduling, and security, AiosDeck abstracts AI capabilities (planning, coding, reviewing, testing, documenting) and provides **agents, memory, scheduling, workflows, and security**.

### What "AI Operating System" Means

| OS Concept | AiosDeck Equivalent |
|-----------|-------------------|
| Process | Agent |
| Scheduler | Task Queue + Workflow Engine |
| Memory (RAM) | Context Engine |
| Disk | Memory Engine (persistent knowledge) |
| Filesystem Permissions | Capability-Based Security |
| Syscalls | Event Bus |
| Kernel | AI Kernel (bootstrap, lifecycle, dispatch) |
| Shell | CLI (`aios`) |
| Drivers | Runtime Adapters (OpenCode, future runners) |
| Containers | ai-jail sandbox |

AiosDeck does not replace the language model. It makes the model a **component** — an execution engine that can be swapped, upgraded, or combined without changing the architecture above it.

### Why Not CrewAI?

CrewAI defines agents, tasks, and crews in Python code. It is a framework for **defining** multi-agent workflows — but it ties you to its Python API, its execution model, and its opinionated structure. AiosDeck is a **platform**, not a framework:

- AiosDeck has its own runtime (not embedded in Python code)
- AiosDeck has security boundaries (capability-based, zero-trust)
- AiosDeck has memory that persists across sessions (not in-memory state)
- AiosDeck is runtime-agnostic (OpenCode today, others tomorrow)

CrewAI asks you to write code to define agents. AiosDeck detects your project and configures agents automatically.

### Why Not LangGraph?

LangGraph is a directed graph framework for LLM workflows. It excels at **model orchestration** — chaining prompts, managing state, routing between nodes. But it operates at the model level:

- LangGraph has no security boundaries between nodes
- LangGraph has no persistent memory engine
- LangGraph does not manage multiple runtimes
- LangGraph requires defining every edge explicitly

AiosDeck operates at the **system level**. It manages agents as processes with capabilities, not functions in a graph. It routes events through a bus, not edges in a DAG. It separates planning from execution from review — not as prompt chains, but as independent agent responsibilities.

### The Real Problem

The fundamental problem AiosDeck solves is not "how to call an LLM from code." That problem is solved ten times over. The real problem is:

1. **Context is lost between sessions.** Every conversation starts from zero.
2. **Memory is not shared.** What one agent learns, another has to re-learn.
3. **Security is an afterthought.** Most tools give the model full filesystem and shell access.
4. **Quality is manual.** The developer must verify every output. There is no automated pipeline.
5. **Workflows are ad-hoc.** No standard way to express "plan → implement → review → test → commit."
6. **Tool lock-in is invisible.** Switching from one LLM to another requires rewriting integration code.

AiosDeck addresses each of these with a dedicated system component — not with a bigger prompt.

## Consequences

### Positive

- **Durability**: Memory survives sessions. The system learns your project over time.
- **Safety**: Zero-trust and capabilities prevent agents from causing damage.
- **Flexibility**: Swap LLMs, runtimes, or agents without restructuring the system.
- **Consistency**: Quality Pipeline ensures every change meets the same standards.
- **Observability**: Audit log records every agent action with timestamps.

### Negative

- **Complexity**: A kernel + event bus + scheduler is more infrastructure than a single script.
- **Learning curve**: Users must understand the agent model, not just prompt engineering.
- **Startup cost**: Detection and context assembly take time before the first interaction.
- **Overhead**: Security, auditing, and pipeline stages add latency to simple operations.

### Neutral

- AiosDeck does not replace OpenCode. It extends it. Users can still use OpenCode directly.
- AiosDeck does not require cloud models. Local-only operation is a first-class use case.
- AiosDeck does not lock you into any Agent model. Agents are pluggable.

## Long-Term Evolution

### Phase 1 — Foundation (v0.1–v0.3)

Establish the core: CLI, Context Engine, Memory Engine, and a single Developer agent. Prove that a coordinated system produces better results than isolated conversations.

### Phase 2 — Specialization (v0.4–v0.6)

Introduce Planner, Reviewer, and Quality Pipeline. Establish the pattern of one-agent-one-responsibility. Prove that a team of narrow agents outperforms a single general-purpose agent.

### Phase 3 — Orchestration (v0.7–v0.8)

Introduce Workflows and a Scheduler that can run agents concurrently. Prove that autonomous agent coordination works reliably for real development tasks.

### Phase 4 — Ecosystem (v0.9–v1.0)

Open extension points for plugins, custom runtimes, community agents, and third-party integrations. Prove that the architecture supports growth beyond the core team.

### Phase 5 — Post-1.0

- **Marketplace**: Community-contributed Agents, Skills, Workflows, and Plugins
- **Team Mode**: Shared memory, shared policies, per-team agents
- **Cloud Gateway**: Optional managed runtime with centralized audit and governance
- **IDE Integration**: In-editor agent panels, inline reviews, side-by-side context
- **Language Server Integration**: Agents that understand your code structurally, not just textually

## Implementation Notes

- [ ] `docs/vision.md` approved — must align with every subsequent ADR
- [ ] Vision statements must be testable: "AiosDeck detects project X without configuration" must map to a test
- [ ] "Why not X" sections must be reviewed when each competitor releases a major version
- [ ] Long-term phases should not constrain MVP architecture — they inform it, not dictate it
