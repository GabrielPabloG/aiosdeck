# ADR-0001 — OpenCode as Runtime

**Status**: Accepted
**Date**: 2026-08-02

## Context

AiosDeck needs a runtime — an execution environment that communicates with language models, loads skills, and runs tools. The runtime is the bridge between the orchestration layer (AiosDeck) and the inference layer (LLMs).

We evaluated four options:

| Option | Description |
|--------|-------------|
| **Build our own** | Write a custom runtime from scratch: prompt construction, tool execution, model abstraction |
| **OpenCode** | Open-source CLI with native skill system, tool execution, and model provider abstraction |
| **LangChain/LangGraph** | Framework with model abstraction and graph-based execution |
| **Direct API calls** | Call OpenAI/Anthropic/Ollama APIs directly without a runtime layer |

## Decision

**Use OpenCode as the primary runtime.** OpenCode provides: a native skill system (SKILL.md), tool execution (file operations, shell, web fetch), model provider abstraction (Ollama, OpenAI, Anthropic, Google), and a CLI interface.

OpenCode is not the only runtime — it is the first. The Runtime Adapter pattern ensures swappability. If OpenCode evolves in a direction that conflicts with AiosDeck's needs, or if a better runtime emerges, only the adapter changes.

## Consequences

### Positive

- **Delegation of complexity**: AiosDeck does not need to implement tool execution, model abstraction, or skill loading. OpenCode already does this well.
- **Skill system alignment**: OpenCode's native skill system is used directly, not wrapped. AiosDeck skills are OpenCode skills.
- **Ecosystem compatibility**: Skills written for OpenCode work in AiosDeck. Skills written for AiosDeck work in standalone OpenCode.
- **Focus**: AiosDeck remains focused on orchestration — not on reinventing a runtime.

### Negative

- **Dependency risk**: OpenCode is an external project. Breaking changes or abandonment would require a new adapter.
- **Version coupling**: AiosDeck must track OpenCode's release cycle for compatibility.
- **Indirect access**: All LLM interactions go through OpenCode. Direct API calls for specialized use cases require the OpenCode adapter to support them.

### Neutral

- The Runtime Adapter abstracts OpenCode. If OpenCode is replaced, no agent code changes.
- OpenCode is always invoked through ai-jail for sandbox isolation. This is an AiosDeck requirement, not an OpenCode requirement.
