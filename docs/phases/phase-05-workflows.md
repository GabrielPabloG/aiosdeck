# Phase 05 — Workflows

**Status**: Implemented
**Level**: Implementation
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Target Version**: v0.7

## Context

Individual agents are powerful. Coordinated agent pipelines are transformative. The Workflow Engine orchestrates multiple agents, quality gates, and decisions into coherent sequences that accomplish high-level goals.

A workflow is not a script. It is a **declarative definition** of which agents run, in what order, with what quality checks, and what happens on failure. The Workflow Engine interprets these definitions and drives the Scheduler through a multi-step process.

## Decision

### Architecture

```
User: aios /feature add-oauth2-login   ← deferred to v0.8
          │
          ▼
    Workflow Engine
          │
          ├── Load workflow definition
          ├── Create task sequence
          ├── Submit to Scheduler
          ├── AgentExecutor guards each stage (v0.5+)
          ├── Monitor progress
          ├── Handle failures (retry, skip, abort)
          └── Report completion
```

### Workflow Definition

Workflows are defined declaratively:

```python
@dataclass
class WorkflowDefinition:
    name: str  # "feature", "fix", "review", ...
    description: str
    stages: list[WorkflowStage]  # Ordered list of stages
    on_failure: FailureStrategy  # retry, skip, abort
    required_capabilities: list[str]  # Capabilities needed by this workflow


@dataclass
class WorkflowStage:
    name: str  # "plan", "implement", "review", ...
    agent: str  # Agent type to execute
    task_type: str  # Type of task to create
    quality_gates: list[str]  # Gates to run after this stage
    on_failure: FailureStrategy  # Override workflow-level strategy for this stage
    depends_on: list[str]  # Previous stage names that must complete first
```

### Built-in Workflows

#### `/feature` — Implement a new feature

```
1. Plan     → Planner: decompose feature into subtasks
2. (Human approval: review and accept plan)
3. For each subtask (ordered by dependency):
   a. Implement → Developer: write code
   b. Quality   → Quality Pipeline: format, lint, test, security
   c. Review    → Reviewer: critique code
   d. Fix       → Developer: address review findings (if any)
   e. Document  → Documentation: update docs if needed
4. Test       → Tester: run full test suite
5. Commit     → Git: stage and commit changes
```

#### `/fix` — Fix a bug

```
1. Implement → Developer: write fix
2. Quality   → Quality Pipeline: format, lint, test
3. Test      → Tester: verify fix with relevant tests
4. Review    → Reviewer: verify fix is correct and minimal
5. Document  → Documentation: update CHANGELOG
6. Commit    → Git: commit with "fix:" prefix
```

#### `/review` — Review existing code

```
1. Review    → Reviewer: full project review
2. Report    → Save review report to docs/
```

#### `/refactor` — Refactor code without changing behavior

```
1. Plan      → Planner: identify refactoring targets
2. Implement → Developer: execute refactoring
3. Test      → Tester: ensure tests still pass
4. Review    → Reviewer: verify behavior unchanged
5. Commit    → Git: commit with "refactor:" prefix
```

#### `/document` — Generate or update documentation

```
1. Analyze   → Documentation: scan codebase for undocumented APIs
2. Generate  → Documentation: create/update documentation files
3. Review    → Reviewer: verify documentation accuracy
4. Commit    → Git: commit with "docs:" prefix
```

#### `/release` — Prepare a release

```
1. Test      → Tester: full test suite
2. Lint      → Quality Pipeline: full lint pass
3. Version   → Git: bump version, create tag
4. Changelog → Documentation: generate changelog from commits
5. Build     → (future: build/publish step)
6. Commit    → Git: commit release changes, push tag
```

### Failure Strategy

| Strategy | Behavior |
|----------|----------|
| `retry` | Retry the failed stage up to N times (configurable, default 3) |
| `skip` | Skip the failed stage and continue. Emit warning. |
| `abort` | Abort the entire workflow. No further stages run. |

Per-stage strategy overrides the workflow-level strategy.

### Workflow State Machine

```
Idle → Running → (stage loop)
                    ├── Stage Started
                    ├── Stage Completed → next stage
                    ├── Stage Failed → retry / skip / abort
                    └── Aborted → Failed
     → Completed (all stages passed)
     → Failed (aborted or max retries exhausted)
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `workflow.started` | Emitted | Workflow execution begins |
| `workflow.stage_changed` | Emitted | Stage transition |
| `workflow.completed` | Emitted | All stages passed |
| `workflow.failed` | Emitted | Workflow aborted |
| `task.created` | Emitted | Create tasks for Scheduler (one per stage) |
| `task.completed` | Consumed | Stage task finished → advance to next stage |
| `task.failed` | Consumed | Stage task failed → apply failure strategy |
| `quality.completed` | Consumed | All gates passed → advance |
| `quality.gate_failed` | Consumed | Gate failed → apply failure strategy |

### CLI Integration

```bash
aios /feature add-oauth2-login          # Full feature workflow
aios /feature add-oauth2-login --skip-review  # Skip review stage
aios /fix auth-token-expiry             # Bug fix workflow
aios /review                            # Code review workflow
aios /refactor extract-auth-module      # Refactoring workflow
aios /document                          # Documentation workflow
aios /release 1.2.0                     # Release workflow
```

### Context Injection

Workflows inject context from the Project Manifest:

```yaml
# .aios/project.yaml
workflows:
  - feature
  - fix
  - review
```

If a workflow is not listed in the manifest, it is still available but may produce a warning (e.g., release workflow on a non-release project).

## Consequences

### Positive

- **Declarative**: Workflows are defined, not programmed. Easy to create new workflows.
- **Standardized process**: Every feature follows the same plan → implement → test → review → commit pipeline.
- **Observable**: Every stage transition emits an event. Progress is visible.
- **Recoverable**: Failure strategies allow workflows to recover from transient errors.

### Negative

- **Rigidity**: Declarative workflows may not suit all development styles. Some teams prefer ad-hoc agent usage.
- **Complexity**: A 6-stage feature workflow can take many minutes to complete.
- **Sequential by default**: Stages run one after another. Parallel stages require v0.8 Scheduler.

### Neutral

- Workflow definitions are YAML/JSON-serializable. Custom workflows can be added via the Plugin System.
- The Workflow Engine does not replace the Scheduler. It creates tasks that the Scheduler manages.

## Implementation Notes

- [x] Implement `workflow/engine.py` — WorkflowEngine orchestrating the fixed pipeline
- [ ] Define separate `workflows/pipelines/*.py` definitions (feature, fix, review, refactor, document, release) — the v1.0 pipeline is code-driven in `workflow/engine.py`; declarative definitions are post-1.0
- [ ] Workflow definition must be serializable to YAML for plugin support — post-1.0
- [x] Failure strategy: abort on failure with graceful skip of optional stages (tester, documentation, git)
- [x] Workflow progress must be reported via the `on_stage` callback ("Stage 3/6: ...")
- [x] Stage dependencies: the pipeline is sequential; each stage advances only when the previous one completes
- [x] Human approval after planning: security approval events (`security.approval_requested` / `approved` / `denied`)
- [x] Test: feature workflow → plan → implement → test → review → commit
- [ ] Test: failed stage with retry strategy → retried up to 3 times — post-1.0 (v1.0 aborts)
- [x] Test: failed stage with abort strategy → workflow aborted immediately
- [x] Test: workflow with no quality gates → stages run without gate checks
