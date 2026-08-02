# Coder Agent

**Status**: Draft
**Date**: 2026-08-02
**Introduced**: v0.2 (as Developer), specialized v0.8

## Context

The Coder is the primary implementation agent. In v0.2–v0.7, it is called the **Developer** and handles all tasks (planning, coding, reviewing, testing, documentation, Git). By v0.8, it is specialized to its true responsibility: writing and modifying code.

The Coder does not plan. It does not review. It does not run tests. It does not commit. It receives a concrete, well-specified task and produces code. This constraint is the key difference between the Developer (which does everything) and the Coder (which does one thing well).

## Decision

### In → Process → Out

```
In:  Task (type: "code", payload: {description: "Implement OAuth2 provider", files: ["src/auth/provider.py"]})
     Context Packet (language, framework, conventions, architecture)
     Skills: ["project-dna", "coding-style"]

Process:
  1. Load project context, conventions, and architecture
  2. Read existing files for context
  3. Generate implementation code
  4. Write files to disk
  5. Report files changed

Out: AgentResult with list of files created/modified
```

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: code) | Consumed | Receive a coding task |
| `agent.completed` | Emitted | Code written successfully |
| `agent.errored` | Emitted | Code generation failed |

### Required Capabilities

- `filesystem_read` — to read existing code for context
- `filesystem_write` — to create and modify files
- `shell` — to run linters and formatters locally (optional, pre-quality gate)

### Cannot

- Plan tasks (that is the Planner's job)
- Review code (that is the Reviewer's job)
- Execute Git commands (that is the Git agent's job)
- Access the internet (that is the Researcher's job)
- Run tests (that is the Tester's job)

### Required Skills

- `project-dna` — must understand project identity, architecture, patterns
- `coding-style` — must follow naming, organization, and convention rules

### Future (v0.8+)

- Multi-file refactoring with awareness of import graphs
- Context-aware code generation (reads surrounding files for style matching)
- Automated test generation alongside implementation

## Consequences

### Positive

- **Single responsibility**: The Coder writes code. Nothing else. Easy to reason about.
- **Security**: Limited capabilities. Cannot push, cannot delete projects, cannot access network.
- **Predictable output**: Given a good task description, output is deterministic within the model's capability.

### Negative

- **Dependency on Planner**: If the task description is poor, the Coder produces poor code.
- **No self-review**: The Coder does not check its own work. Quality depends on the Quality Pipeline.
- **Context limitations**: The Coder reads files, but does not understand the full system impact of changes.

### Neutral

- The Developer agent (v0.2–v0.7) handles all responsibilities. The Coder is its successor.
- Code generation quality depends on the underlying LLM. The Coder is an orchestrator, not a model.

## Implementation Notes

- [ ] Implement `agents/coder.py` — CoderAgent class (v0.8)
- [ ] Implement `agents/developer.py` — DeveloperAgent class (v0.2, handles all task types)
- [ ] Coder must read existing files before generating code (for context)
- [ ] Coder must write files through the Security Manager (path validation)
- [ ] Coder must never execute Git, internet, or test commands
- [ ] Test: coding task → files created with expected content
- [ ] Test: coder denied git capability → Security Manager blocks
- [ ] Test: coder with empty task → error, no files written
