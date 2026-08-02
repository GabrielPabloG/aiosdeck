# Quality Pipeline

**Status**: Proposed
**Date**: 2026-08-02

## Context

AiosDeck is not just a code generator. It is responsible for ensuring that generated code meets the project's standards — stylistic, functional, architectural, and security-related. Without automated quality checks, the developer must manually review every agent output. That defeats the purpose of automation.

The Quality Pipeline is a sequence of automated gates that every code change must pass before being accepted. If a gate fails, the task returns to the agent for correction. The pipeline is fully automated and project-aware — it detects which tools to use, never asking the developer to configure them.

The principle is: **automation over prompts**. The project decides which quality checks run, not the developer.

## Decision

### Architecture

```
Agent Output ──► Quality Pipeline
                    │
    ┌───────────────┼───────────────┬──────────────┬──────────────┐
    ▼               ▼               ▼              ▼              ▼
Format Gate    Lint Gate      Test Gate     Security Gate   AI Gates
    │               │               │              │              │
    ├── black       ├── ruff        ├── pytest     ├── bandit     ├── AI Arch Review
    ├── prettier    ├── eslint      ├── vitest     ├── trivy      │
    ├── cargo fmt   ├── clippy      ├── bats       └── semgrep    └── Docs Review
    └── shfmt       └── shellcheck  └── cargo test
```

### Gate Sequence

Gates execute in a fixed order. If a gate fails, subsequent gates are skipped. The failure is reported and the task returns to the agent.

```
1. Format    → Is the code properly formatted?
2. Lint      → Are there any static analysis issues?
3. Tests     → Do all tests pass?
4. Security  → Are there any vulnerabilities?
5. AI Arch   → Does the change respect architecture? (AI agent)
6. Docs      → Is documentation updated? (AI agent)
```

### Gate Interface

Every gate implements the same protocol:

```python
class QualityGate(Protocol):
    name: str
    command: str | None          # CLI command to run, None for AI gates
    auto_detect: bool = True     # Detect tool from project context

    async def run(self, files: list[str], context: ContextPacket) -> GateResult: ...
    async def is_applicable(self, context: ContextPacket) -> bool: ...
```

### Auto-Detection (Project Profile)

The Quality Pipeline does not require configuration. It detects the right tools from the Context Packet:

| Language | Format | Lint | Tests | Security |
|----------|--------|------|-------|----------|
| Python | black | ruff | pytest | bandit / semgrep |
| JavaScript/TypeScript | prettier | eslint | vitest / jest | semgrep |
| Rust | cargo fmt | clippy | cargo test | cargo audit |
| Shell | shfmt | shellcheck | bats | shellcheck |
| Go | gofmt | golangci-lint | go test | gosec |

If a tool is not installed, the gate is skipped with a warning. No gate failure, no blocking. The developer installs tools as needed.

### Gate Configuration Override

The Project Manifest can override auto-detected values:

```yaml
# .aios/project.yaml
quality:
  lint: ruff            # Override: use ruff even if eslint is detected
  format: black
  tests: pytest --cov   # With custom arguments
  security: bandit
```

### Gate Results

```python
@dataclass
class GateResult:
    gate_name: str
    status: GateStatus       # passed, failed, skipped, error
    output: str              # Command output for debugging
    duration_ms: int
    suggestions: list[str]   # How to fix failures (for agents)

class GateStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"     # Tool not installed
    ERROR = "error"         # Gate execution error
```

### AI Quality Gates

The last two gates are not tool-based. They are AI-driven reviews:

#### Architecture Review

The Reviewer agent evaluates whether the change:
- Respects the project's architecture patterns
- Follows established conventions
- Introduces no circular dependencies
- Maintains appropriate module sizes
- Does not duplicate existing functionality
- Preserves backward compatibility

```python
class ArchitectureReviewGate:
    name = "architecture_review"
    command = None  # AI agent, not a CLI tool

    async def run(self, files: list[str], context: ContextPacket) -> GateResult:
        review_prompt = self._build_review_prompt(files, context)
        result = await self.runtime.execute(Task(type="review", ...), context, ["project-dna"])
        return self._parse_review_result(result)
```

#### Documentation Review

The Reviewer agent checks:
- Are API changes reflected in documentation?
- Is the README updated if relevant?
- Are ADR documents created for architectural changes?
- Is the CHANGELOG updated?

```python
class DocumentationReviewGate:
    name = "documentation_review"
    command = None

    async def run(self, files: list[str], context: ContextPacket) -> GateResult:
        if not self._has_api_changes(files):
            return GateResult(status=GateStatus.SKIPPED)
        # Review documentation coverage
        ...
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `agent.completed` | Consumed | Agent output ready for quality checks |
| `quality.started` | Emitted | Pipeline execution begins |
| `quality.gate_passed` | Emitted | Individual gate passed |
| `quality.gate_failed` | Emitted | Individual gate failed |
| `quality.completed` | Emitted | All gates passed (or pipeline aborted) |
| `task.created` | Emitted | Gates failed → new task created for agent fix |

### Pipeline Integration Flow

```
1. Agent emits agent.completed
2. Quality Pipeline starts
3. For each gate:
   a. Check if gate is applicable (tool installed, files to check)
   b. Run gate
   c. If passed → next gate
   d. If failed → emit quality.gate_failed → abort pipeline
4. If all gates pass → emit quality.completed
5. If any gate fails → emit quality.gate_failed + create fix task
```

Failed gates create a new task:

```python
async def on_gate_failed(self, gate_result: GateResult, original_task: Task) -> None:
    fix_task = Task(
        type="code",
        priority=TaskPriority.HIGH,
        payload={
            "description": f"Fix {gate_result.gate_name} issues:\n{gate_result.suggestions}",
            "original_task_id": original_task.id,
            "gate_output": gate_result.output,
        }
    )
    await self.bus.publish("task.created", fix_task)
```

## Consequences

### Positive

- **Consistency**: Every change passes the same checks. No manual review required for mechanical issues.
- **Auto-detection**: Works out of the box for common languages. No configuration.
- **Comprehensive**: Covers formatting, linting, testing, security, architecture, and documentation.
- **Feedback loop**: Failed gates generate fix tasks automatically. The system improves itself.

### Negative

- **Latency**: Running 6 gates sequentially can be slow (especially tests and AI reviews).
- **Tool dependency**: Missing tools cause skipped gates. The developer must install tools to get full coverage.
- **AI gate accuracy**: Architecture and documentation reviews depend on the Reviewer agent's quality.

### Neutral

- AI gates are optional in v0.6. The pipeline can run with only tool-based gates.
- Gate order is configurable via the Project Manifest (future feature).

## Implementation Notes

- [ ] Implement `quality/pipeline.py` — Orchestrates gate execution in sequence
- [ ] Implement `quality/gates/format.py` — Format gate with auto-detection
- [ ] Implement `quality/gates/lint.py` — Lint gate with auto-detection
- [ ] Implement `quality/gates/tests.py` — Test gate with auto-detection
- [ ] Implement `quality/gates/security_gate.py` — Security gate with auto-detection
- [ ] Implement `quality/gates/architecture_review.py` — AI-driven architecture review
- [ ] Implement `quality/gates/documentation_review.py` — AI-driven documentation review
- [ ] Auto-detection: use Context Packet to choose correct tools per language
- [ ] Gate Skipping: if tool is not installed, skip with warning (not fail)
- [ ] Test: Python project → black + ruff + pytest gates run
- [ ] Test: JS project → prettier + eslint + vitest gates run
- [ ] Test: failing gate → pipeline aborts → fix task created
- [ ] Test: all gates pass → quality.completed emitted
- [ ] Test: missing tool → gate skipped with warning
