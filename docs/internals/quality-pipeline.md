# Quality Pipeline

**Status**: Implemented
**Date**: 2026-08-08

## Context

AiosDeck is not just a code generator. It is responsible for ensuring that generated code meets the project's standards — stylistic, functional, architectural, and security-related. Without automated quality checks, the developer must manually review every agent output. That defeats the purpose of automation.

The Quality Pipeline is a sequence of automated gates that every code change must pass before being accepted. If a gate fails, the workflow stops (fail-fast) unless an explicit policy override applies. The pipeline is fully automated and project-aware — it detects which tools to use, never asking the developer to configure them.

The principle is: **automation over prompts**. The project decides which quality checks run, not the developer.

## Security posture

Every decision in the pipeline follows the AiosDeck philosophy:

- **Fail-safe**: missing policy, unknown environment, or a gate that errors all **block** — failure closes, never opens.
- **Observability**: every gate run is persisted (`telemetry_gates`) and every workflow run emits `quality.*` events.
- **Zero regression**: without a `quality_config` the pipeline is byte-identical to the previous behavior.
- **Config-driven decisions**: overrides come from YAML, never from an interactive CLI prompt.
- **Auditable**: every block/override decision is serializable (`DecisionResult.to_dict()` + `overridden` column).

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
    command: str | None  # CLI command to run, None for AI gates
    auto_detect: bool = True  # Detect tool from project context

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
    status: GateStatus      # passed, failed, skipped, error
    reason: str             # human-readable outcome
    findings: list[GateFinding]  # structured findings, never loose text
    metadata: dict

    def to_dict(self) -> dict: ...  # audit-safe JSON serialization
```

Findings carry the canonical severity vocabulary `low | medium | high | critical`,
mapped from reviewer detectors (`info | warning | error`) via
`severity_mapper()` in `aios/quality/contracts.py`.

### Gate Policy

Decisions are resolved in `aios/quality/policy.py` via `resolve_decision()`.

| Severity | dev | release |
|----------|-----|---------|
| critical | BLOCK | BLOCK |
| high     | BLOCK | BLOCK |
| medium   | WARN  | BLOCK |
| low      | WARN  | WARN |
| (none)   | PASS  | PASS |

- **Fail-safe default**: no policy → the conservative default applies
  (`DEFAULT_POLICY`). Unknown environment → any finding blocks.
- **Gate error** → blocks (fail-safe).
- **Overrides**: explicit, auditable, must match `gate` + `environment`; an
  override lifts a block (`overridden=True`) and records the reason. Never
  interactive — configured in YAML.

```yaml
# ~/.config/aiosdeck/config.yaml
quality:
  environment: release
  policy:
    release: [critical, high, medium]
  overrides:
    - gate: code_gate
      environment: dev
      reason: manual inspection passed
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
| `quality.started` | Emitted | Pipeline run begins (workflow, gates active) |
| `quality.gate_started` | Emitted | Individual gate begins |
| `quality.gate_completed` | Emitted | Gate finished without blocking (passed/skipped/failed-warn) |
| `quality.gate_blocked` | Emitted | Gate finished and blocked the run |
| `quality.completed` | Emitted | Pipeline run finished |

**Canonical gate payload** (both terminal events; `correlation_id = run_id`):

```json
{
  "gate": "code_gate",
  "status": "failed",
  "duration_ms": 312.4,
  "findings": {"low": 0, "medium": 1, "high": 3, "critical": 0},
  "blocked": true,
  "overridden": false,
  "reason": "blocking severity: high"
}
```

Events are only emitted while a `quality_config` is active (zero events
otherwise), and a failing subscriber never crashes the run — `EventBus.publish`
isolates subscriber errors.

### Pipeline Integration Flow

Gates run inside `WorkflowEngine` as `WorkflowStage`s, in a fixed order:

```
developer* → code_gate → reviewer → security_gate → tester → test_gate
→ documentation → documentation_gate → git
(release_gate runs last when environment == "release")
```

```
1. Run gate
2. passed            → advance to next stage
3. failed + policy   → BLOCK: fail-fast (stage recorded, run stops)
                       WARN : advance, annotated (warn)
                       override → advance, annotated (overridden)
4. skipped           → advance, annotated (skipped)
5. error             → block (fail-safe)
```

Each terminal outcome is emitted as `quality.gate_completed` or
`quality.gate_blocked` and persisted by the TelemetryEngine.

## Consequences

### Positive

- **Consistency**: Every change passes the same checks. No manual review required for mechanical issues.
- **Comprehensive**: Covers formatting, linting, testing, security, and documentation.
- **Observability**: Every gate run is persisted and queryable (`aios quality stats`).
- **Fail-safe**: Missing policy/tooling/unknown environment never silently opens the pipeline.

### Negative

- **Latency**: Running gates sequentially adds time (especially tests).
- **Tool dependency**: Missing tools cause skipped gates. The developer must install tools to get full coverage.

### Neutral

- Gates are optional in v0.9: without a `quality_config` the pipeline is unchanged.
- The pipeline currently targets Python projects (ruff, pytest); per-language auto-detection is future work.

## Implementation Notes

- [x] `aios/quality/contracts.py` — `GateStatus`, `Severity`, `GateInput`,
  `GateFinding`, `GateResult`, `QualityGate` protocol, `severity_mapper`
- [x] `aios/quality/gates/` — `CodeGate` (ruff), `TestGate` (TesterAgent report),
  `SecurityGate` (detectors + mapper), `DocumentationGate` (CHANGELOG/TODO),
  `ReleaseGate` (skeleton, skipped)
- [x] `aios/quality/policy.py` — severity × environment decision matrix,
  fail-safe default, auditable overrides
- [x] `WorkflowEngine` — gates as `WorkflowStage`s, fail-fast on block,
  annotated advance on skip/warn/override
- [x] `quality.*` events on the bus (only while gates are active)
- [x] `telemetry_gates` table + `aios quality stats` read-side
- [x] CLI gate trail on `aios plan --run` (human PASS/FAIL/SKIP + `--json`)
- [ ] AI-driven architecture/documentation review gates (future)
- [ ] Per-language tool auto-detection (future)
