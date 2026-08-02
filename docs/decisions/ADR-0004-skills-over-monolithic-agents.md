# ADR-0004 — Skills over Monolithic Agents

**Status**: Accepted
**Date**: 2026-08-02

## Context

Agents need knowledge. A Coder agent writing Python code needs to know: the project's architecture, its coding conventions, its testing patterns, its Docker setup, its Git workflow. Without this knowledge, the agent produces generic, non-idiomatic code.

We evaluated three approaches to agent knowledge:

| Option | Description |
|--------|-------------|
| **Prompt injection** | Include all knowledge in the system prompt. One giant prompt per agent session. |
| **Fine-tuned models** | Train a model on the project's codebase. Expensive, brittle, slow. |
| **Skills (modular knowledge)** | Small, reusable knowledge fragments loaded on-demand. One skill = one domain. |

## Decision

**Use Skills as the mechanism for agent knowledge.** Each Skill is a small, self-contained `SKILL.md` file that teaches one specific domain. Skills are loaded on-demand by the Runtime Adapter before each agent task. AiosDeck does not create its own skill system — it uses OpenCode's native skill mechanism.

The Coder does not know everything. It learns by loading Skills: `project-dna` (identity and architecture), `coding-style` (conventions), `bash-style` (shell conventions), `docker-lifecycle` (container patterns).

## Consequences

### Positive

- **Modularity**: Adding a new technology to the project means adding a Skill, not rewriting a prompt.
- **Reusability**: Skills are shared between agents. The `project-dna` skill is loaded by Planner, Coder, Reviewer, and Documentation agent.
- **Separation of concerns**: Knowledge is separated from agent logic. Agents are execution engines. Skills are knowledge.
- **Project-specific**: Skills can be project-level (`.opencode/skills/`), user-level (`~/.config/opencode/skills/`), or core (shipped with AiosDeck).
- **Alignment with OpenCode**: Skills are an OpenCode feature. AiosDeck uses them, does not reinvent them.

### Negative

- **Skill discovery**: Agents must know which skills to load. Missing a required skill produces poor output. The project manifest and agent configuration define the skill list.
- **Versioning**: Skills evolve. A skill that changes format may break agent expectations. Skill versioning is a future concern.
- **Loading overhead**: Each skill adds to the context window. Loading too many skills degrades performance.

### Neutral

- Skills do not replace agents. They augment them. The architecture still has specialized agents — the Coder loads coding skills, the Reviewer loads review skills.
- The first two core skills (`project-dna`, `coding-style`) are enough for v0.1. Additional skills are born when a problem demands them.
