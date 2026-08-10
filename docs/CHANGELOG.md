# Changelog

All notable changes to AiosDeck are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-08-10

### Added

- **Stabilization v1.0** — hardening, simplification, and documentation coherence
  toward the first stable release.
  - **S0 Contracts Freeze** — contract tests for all 9 agents + base + executor
    (input/output/error codes stable); `docs/internals/ownership-matrix.md`
    (domain boundaries + contract freeze table); frozen signatures for
    `AgentTask`, `AgentResult`, `ExecutionRequest`, `ExecutionOutcome`,
    `RunResult`, `StageSummary`, `IntentPolicy`, `EffectivePermissions`.
  - **S1 Reliability** — `stage_to_summary` mapper contract tests
    (WorkflowStage ↔ StageSummary); timeout/retry/error-mapping freeze;
    `docs/fire-test.md` generalized to a stabilization fire test (minimal
    telemetry: executions + tokens + cost; `aios ocean`, help, completion).
  - **S2 Security Closure** — intent enforcement extracted to
    `security/intent_validator.py` (auditable allow/deny decision); security
    event coverage audit; fail-safe resolver defaults reviewed.
  - **S3 Simplification & Dedup** — `routing/ranker.py` removed (dead code);
    skills discovery single-sourced in `SkillRegistry`;
    `format_skill_header()` shared between retrieval and PromptBuilder;
    CLI restructured into `cli/commands/` package (core/exec_cmds/memory)
    with central registry.
  - **S4 Docs & Product Parity** — CHANGELOG restructured (one section per
    version); Status blocks on README/vision/philosophy/architecture; ADR
    metadata standardized; false claims fixed (Coder→developer.py, Reviewer CLI,
    workflows implemented, `.aios/memory.db` path); phase/agent statuses
    updated; stabilization roadmap (S0-S5) replaces rigid plans;
    `docs/migration-1.0.md` guide. Package layout in `docs/architecture.md`
    rewritten to mirror `src/aios/` (events/ not event_bus/, workflow/ not
    workflows/pipelines/, security/intent_validator|resolver|capabilities|
    actions|contracts, integrations/projdesk/; backlog, learning, knowledge,
    retrieval, routing, skills, telemetry, usage, prompts, research, ui,
    storage added); README Getting Started marked v1.0-rc1; phase-01/04/05/06
    implementation notes aligned with the shipped code.
  - **S5 RC/GA** — Backlog Runner integrated (v0.9.13 feature brought forward);
    CLI surface frozen with the full top-level command tree);
    `docs/release-checklist.md`; version
    bumped to `1.0.0-rc1`; v1.0 labeling documented in `docs/architecture.md`.
    S5.1 RC checks 2026-08-10: 1344 tests green, ruff clean, circular imports
    verified, contract + architecture gates pass. Fire-test telemetry gates
    rewritten for v1.0 (executions + routing mandatory; token/cost when the
    provider reports usage); known limitations documented.

### Changed

- `docs/internals/ownership-matrix.md` — new; defines the ownership boundaries
  and the v1.0 contract freeze.
- `docs/CHANGELOG.md` — restructured into one section per version
  (v0.9.5..v0.9.13 released, [Unreleased] only carries stabilization work).
- `docs/fire-test.md` — generalized from a v0.9.11 routing guide to a
  stabilization fire test.
- `aios backlog run` — gains `--branch`/`--no-branch` flags to create a
  per-task branch (`feature/<slug>-<id>`) or commit on the current branch
  (default remains no branch).

## [0.9.13] - 2026-08-09

### Added

- **Backlog Runner** — process N tasks from a backlog automatically.
  - **Models** — `BacklogTask` and `BacklogRunResult` with conventional commit
    parsing (`type(scope): subject (vX.Y.Z)`).
  - **Parser** — `parse_conventional`, `load_tasks_from_kanban(board)`,
    `load_tasks_from_file(path)`.
  - **Runner** — `BacklogRunner` executes tasks sequentially through
    `Kernel.run(mode="plan-run")` with per-task commit factories,
    `create_branch=False`, and kanban `InProgress` → `Done`/`blocked` flow.
  - **CLI** — `aios backlog run/list/add/stats` with `--continue`, `--from N`,
    `--source=board:NAME | file:PATH`.
  - **Telemetry** — `telemetry_backlog` table, `insert_backlog_run`,
    `query_backlog_stats`, and `backlog.*` events in `ALL_TOPICS`.
  - **Workflow** — additive `commit_factory` and `create_branch` params on
    `WorkflowEngine.execute` and `Kernel.run` (defaults byte-idéntico).

## [0.9.12] - 2026-08-09

### Added

- **Ocean Console** — a dark, marine dashboard for `aios ocean`, rendered
  entirely through semantic design tokens.
  - **Theme** — `Theme`/`ColorResolver`/`ColorMode` (`COLOR`/`256`/`MONO`)
    with `detect_color_mode` (`NO_COLOR` kill switch) and the deep-water
    `ocean_theme`; widgets consume tokens via the resolver, never raw ANSI.
  - **Components** — `render_panel`, `render_progress`, `render_status_pill`,
    `render_metric_card`, `render_section_header`, `render_table`, driven by
    `RenderContext` (`width`/`height`/`compact`); collapsible when the
    terminal is under 80 columns or 24 rows.
  - **Overview** — data-driven `render_page` composed from `datasources.py`
    (`overview_data`, `workflows_data`, `agents_data`, `skills_data`,
    `knowledge_data`, `usage_data`, `quality_data`, `settings_data`), with safe
    empty states.
  - **TUI** — interactive loop (keys `1..8`, `tab`, `Shift+tab`, `r`, `q`)
    that blocks on input and redraws per key; static fallback when not a TTY;
    `aios ocean [--page NAME] [--once] [--json] [--refresh N]`.
  - **Settings `--save`** — `settings_io` (`load_ui_section` /
    `save_ui_section`) persists only the `ui:` section of
    `~/.config/aiosdeck/config.yaml` atomically; PyYAML is a soft dependency
    (no-op when absent); never writes without `--save`.
  - **Routing pricing** — `_MODEL_PRICING` now prices openrouter models
    (`deepseek-v4-flash` 0.068, `qwen3-coder` 0.22, `gpt-5-mini` 0.30,
    `claude-sonnet-4-5` 3.0 per 1M input tokens); `_estimate_cost` super-
    estimates output (3× input, fail-closed) and `cost_cap` forces the cheap
    fallback when a primary exceeds the budget.

## [0.9.11] - 2026-08-08

### Added

- **Model Router** — separates model decision from agent execution. Policy
  rules (and, later, telemetry data) pick the model; agents only describe what
  they are doing.
  - **Contracts** — `RouteInput` (agent/task_type/complexity/context_size/
    model_override) and `RouteDecision` (provider/model/variant/reason/
    estimated_cost/fallback_chain/source); `ModelRouter` protocol with
    `route(input) -> RouteDecision`.
  - **Policy engine** — `RuleBasedRouter` matching on `agent` + `complexity`
    with `context_limits`, `cost_cap` (re-routes to the cheapest fitting
    fallback or errors), `fallback_providers`, and deterministic `reason`
    (`policy:<index>` | `heuristic:default` | `explicit_override`).
  - **Override** — explicit `model=` in `RuntimeEngine.execute` skips the
    router and is audited (`source="override"`); agents never hardcode models.
  - **Runtime integration** — `execute(..., agent, task_type, complexity,
    context_size, model="")`; `OpenCodeAdapter` inserts `-m`/`--variant` before
    `--auto`; fallback loop over the chain with typed `RouteFallbackExhausted`
    (never loops). Byte-identical to v0.9.10 when routing is unconfigured.
  - **Telemetry** — `runtime.route_selected` event + `telemetry_routing` table
    (agent, provider, model, reason, estimated_cost, context_size,
    fallback_used/reason, correlation_id); `query_routing_stats/records` and
    `route_accuracy` (estimated vs actual cost when both are available).
  - **Config** — `RouteConfig` with `enabled`, `default_provider/model/variant`,
    `rules`, `cost_cap`, `context_limits`, `fallback_providers`; env
    `AIOS_ROUTING_ENABLED`/`AIOS_ROUTING_COST_CAP` + YAML section `routing:`.
  - **CLI** — `aios route explain --agent A [--task-type] [--complexity]
    [--context-size] [--json]`, `aios route stats [--agent] [--model]
    [--limit] [--records] [--json]`, `aios route stats --accuracy`.

## [0.9.10] - 2026-08-08

### Added

- **Learning Governance** — event-driven observation capture, deterministic
  advisor, and approval-gated ingestion into project memory.
  - **Contracts** — `ObservationRecord`, `LearningCandidate`,
    `ConfidenceScore`, `ReviewDecision`, `Advisor` protocol (pluggable for
    future LLM advisors), `ReviewPolicy` with default fail-safe (everything
    requires human approval unless explicitly opted into `auto` via policy).
  - **Extractor** — deterministic confidence from gate severity
    (`critical`→0.9, `high`→0.7, `medium`→0.5, `low`→0.3), type mapping
    (`gate finding`→`mistake/pattern`, `research memory_candidate`→memory
    type), SHA-256 deduplication, recurrence counting for agent failures.
  - **Advisor** — `RulesAdvisor` (deterministic, `advisor="rules-advisor"`)
    recommends `approve|reject|needs_human` based on confidence, risk, and
    type. High/critical risk or decision/architecture types always require
    human review.
  - **Ingestion** — `approve` → `ingest` pipeline blocked until `approved`;
    maps candidate types to `MemoryEngine.remember_*` (convention/decision/
    pattern/mistake); versioned (`ingest_version`, `ingested_memory_id`);
    complete audit trail via `learning_reviews`.
  - **Event-driven** — subscribes to `quality.gate_*`, `agent.execution.failed`,
    `research.completed` (new); emits `learning.observation_recorded`,
    `learning.candidate.*`, `learning.ingested`.
  - **CLI** — `aios learning candidates [--state] [--limit] [--json]`,
    `aios learning approve <id>`, `aios learning reject <id> --reason "..."`,
    `aios learning ingest <id>`, `aios learning export [--format md] [--out]`.
    Reject requires `--reason`; ingest blocks without approval.
  - **Config** — `LearningConfig` with `enabled`, `auto_capture`,
    `confidence_threshold`, `min_evidence`, `recurrence_threshold`, `policy`;
    env `AIOS_LEARNING_ENABLED` + YAML section `learning:`.

## [0.9.9] - 2026-08-08

### Added

- **Context Layers** — formalizes context as explicit layers
  Global→User→Project→Task→Research→Retrieved with deterministic composition
  and token economy.
  - **Layer contracts** — `LayerType` (six layers), `LAYER_PRECEDENCE`
    (operational ordering `TASK > USER > PROJECT > GLOBAL > RESEARCH >
    RETRIEVED`), `GUARDRAIL_LAYERS` (`TASK`), `Layer` (type/content/source/
    guardrail/tokens/trace), and `LayeredContext` with `empty_layers()`
    fallback factory.
  - **Assembly** — `assemble_layers` = order → sha256 dedupe (first-by-
    precedence wins) → truncate within absolute per-layer caps and the agent
    budget, reusing `_truncate_to_tokens`. Guardrails are immutable: never
    truncated or dropped.
  - **ContextAssembler** — collects raw layers (project packet, task
    description, research summary, retrieved chunks) within
    `ContextBudget.for_agent(agent)`. Retrieved excludes
    `_SKILL_SOURCE_TYPES` (skills stay in the SkillAssembler path). Per-layer
    collection is fail-safe (failure → empty layer).
  - **Layered prompts** — `PromptBuilder.build(..., layered=...)` composes
    deterministic sections + an `[Audit]` block; `layered=None` is
    byte-identical to v0.9.8.
  - **Wiring** — `_build_context_assembler` in `cli/main.py` injects the
    assembler into Developer/Planner agents (SkillAssembler pattern); absent
    assembler keeps the previous prompt.
  - **CLI** — `aios plan --debug-context` renders the layer tree (text or
    `--json`) with per-layer source/tokens/guardrail/trace and the audit trail.

### Changed

- `docs/internals/context-layers.md` — layer model, precedence, budgets, and
  wiring documented.

## [0.9.8] - 2026-08-08

### Added

- **Intent & Policy** — granular security policy enforced at the executor and
  runtime boundaries.
  - **Contracts** — `IntentPolicy` (explicit `actions` + `deny`, frozen,
    deterministic `to_dict()`), `EffectivePermissions` (sorted serialization,
    `allows`), and `SecurityDecision` (auditable verdict). `AgentCapabilities`
    is reused from `agents/contracts`.
  - **Granular vocabulary** — additive, deterministic `CAPABILITY_ACTIONS`
    expansion table mapping each coarse capability to granular actions
    (`filesystem.read`, `shell.execute`, `git.branch`, `git.commit`,
    `network.access`, ...). Unmapped capabilities grant nothing (fail-safe).
    Safe `DEFAULT_INTENTS` pinned by tests; `release` has no default and
    destructive actions (`filesystem.delete`, `git.push`, `git.tag`,
    `network.access`, `release.publish`) are never implicit.
  - **Resolver** — `effective = (intent.actions - intent.deny) ∩
    expand(capabilities)`; deny = absence, explicit deny always wins, an intent
    never elevates capabilities. `decide()` returns a full `SecurityDecision`
    with reason and violations.
  - **Executor boundary** — opt-in run-gate: an intent resolves against the
    agent's coarse capabilities; an empty effective set is a structured
    `PERMISSION_DENIED` (never a silent fallback). The intent is attached to
    the run context for the agent. `intent=None` is byte-identical.
  - **Workflow intent** — the pipeline runs under `WORKFLOW_INTENT` (develop
    defaults + `ask_user`), respecting a caller-supplied override on the
    context. Stage details expose the effective permissions and intent.
  - **Runtime mapping** — `OpenCodeAdapter` derives the least-privilege
    `OPENCODE_PERMISSION` from effective permissions: `question` always denied,
    `read/glob/grep` ↔ `filesystem.read`, `edit` ↔ `filesystem.write`,
    `webfetch/websearch` ↔ `network.access`, and a bash policy that explicitly
    denies `git push`, `git tag`, `rm -rf`, `curl`, `wget` while allowing the
    run's commands (`git branch`, `git commit`, `grep`, `ruff`, `python`,
    `pytest`) — the denies survive `--auto`.
  - **Audit trail** — `security.intent.applied` / `security.check.passed` /
    `security.check.denied` events persisted into the additive
    `telemetry_security` table with `insert_security_decision`,
    `query_security_stats`, and `query_security_records`. Zero events without
    an intent.
  - **CLI** — `aios policy show` (canonical capabilities, default intents,
    expansion table), `aios security stats` (queryable allow/deny trail), and a
    plan intent summary (`intent: develop (source: default)` with effective
    permissions per stage) on `aios plan --run`.

### Changed

- `docs/internals/security.md` — Policy Engine note updated; **Intent vs
  Capability vs Enforcement** section added.

## [0.9.7] - 2026-08-08

### Added

- **Quality Pipeline / Gates** — automated gates enforced by the workflow
  between agent stages.
  - **Gate contracts** — `GateStatus`, `Severity` (canonical
    `low|medium|high|critical`), `GateInput`, `GateFinding`, `GateResult`
    (structured, never loose text, audit-safe `to_dict()`), and the
    `QualityGate` protocol.
  - **Concrete gates** — `CodeGate` (ruff check + format --check),
    `TestGate` (wraps the TesterAgent report; `failed == 0 → passed`),
    `SecurityGate` (deterministic `scan_secrets`/`scan_unsafe` + severity
    mapper), `DocumentationGate` (CHANGELOG/TODO skeleton), and `ReleaseGate`
    (skeleton, skipped). All local, deterministic, no network or LLM.
  - **Policy engine** — `resolve_decision()`: `critical`/`high` always block,
    `medium` blocks in release / warns in dev, `low` warns, no policy →
    fail-safe default, unknown environment → block, explicit auditable
    overrides (gate + environment).
  - **Workflow integration** — gates run as `WorkflowStage`s in the order
    `developer* → code_gate → reviewer → security_gate → tester → test_gate →
    documentation → documentation_gate → git` (`release_gate` last in release).
    Fail-fast on block, annotated advance on skip/warn/override. Opt-in via
    `quality_config`; without it the pipeline is unchanged.
  - **Event bridge** — `quality.started` / `quality.gate_started` /
    `quality.gate_completed` / `quality.gate_blocked` / `quality.completed`
    with a canonical payload (gate, status, duration_ms, findings per severity,
    blocked, overridden, reason) and `correlation_id = run_id`. Emitted only
    while gates are active.
  - **Gate telemetry** — additive `telemetry_gates` table (findings per
    severity, block decision, overridden, correlation_id, project_id) with
    `query_gate_stats` / `query_gate_records`.
  - **CLI** — `aios plan <intent> --run` renders a PASS/FAIL/SKIP gate trail
    (with warn/override annotations); `--json` emits full structured findings;
    new `aios quality stats [--gate|--status|--limit|--records|--json]`
    read-side.
  - **Config** — `QualityConfig` extended with `environment`, `policy`, and
    `overrides`, loadable from the user config YAML.

### Changed

- `docs/internals/quality-pipeline.md` status moved from **Proposed** to
  **Implemented** with the gate policy and canonical event contract documented.

## [0.9.6] - 2026-08-08

### Added

- **Intelligent Skills / Living Skills** — skills evolve from static files into
  measurable, retrievable-by-intent knowledge assets with lifecycle telemetry.
  - **Skill metadata schema** — `SkillMetadata` dataclass with `name`,
    `description`, `triggers`, `scope`, `dependencies`, `priority`, `status`,
    `version`, and `schema_version` field. Strict frontmatter validation on
    load.
  - **SkillRegistry** — loads validated skill metadata from
    `.opencode/skills/*/SKILL.md`, filtering deprecated skills by default.
  - **SkillDiscoveryService** — deterministic, explainable intent-based skill
    ranking by trigger match (0.50), scope match (0.30), and priority (0.20).
    Each `ScoredSkill` carries its own `trigger_matches` and `scope_matches` for
    audit trails.
  - **SkillRetrievalService** — maps discovered skills to Knowledge Store chunks
    with per-skill chunk policy (top-N chunks per skill), respecting
    `ContextBudget` per agent. Generic retriever layer unchanged.
  - **SkillAssembler** — explicit fallback boundary: discovery → retrieval →
    `SkillContext[]`. Any failure returns `[]`, and agents fall back to the
    static `required_skills` path (byte-identical prompt to v0.9.5).
  - **PromptBuilder smart skills section** — renders budgeted skill chunks with
    audit trail (considered/selected/used/dropped, budget consumed). Optional
    `skill_contexts` parameter; `None`/`[]` preserves the golden path.
  - **Skill telemetry** — `telemetry_skills` table with lifecycle signals
    (`considered`, `selected`, `used`, `relevance_score`, `tokens_contributed`,
    raw `downstream_success`). `SkillUsageRecorder` emits one row per skill per
    invocation.
  - **Skills CLI** — `aios skills discover <intent>` (ranked candidates + score
    breakdown), `aios skills inspect <name>` (metadata + index status), and
    `aios skills stats` (per-skill lifecycle metrics).

### Changed

- DeveloperAgent and PlannerAgent accept optional `skills` (SkillAssembler)
  injected by the kernel factory. Skills are only assembled when available;
  otherwise behavior is unchanged.

## [0.9.5] - 2026-08-08

### Added

- **Local Retrieval / RAG** — context-aware retrieval with per-agent token
  budgets, keyword and vector retrievers, and compression metrics.
  - **EmbeddingProvider contract** — protocol-based interface (`embed`,
    `dimensions`, `available`, `name`) with `OllamaEmbeddingProvider`
    implementation using Ollama's `/api/embed` endpoint (stdlib-only, zero
    external deps).
  - **KeywordRetriever** — lexical overlap scoring over FTS5 results. Always
    active; no external dependencies.
  - **VectorRetriever** — cosine similarity over stored embeddings (opt-in via
    `--vector` flag). Falls back gracefully to keyword when embeddings are
    missing or Ollama is unavailable.
  - **ContextSelector** — `retrieve(20) → rank → dedupe → select(≤ budget)`
    pipeline with source-type boosts, per-source deduplication, token-budget
    enforcement, and oversized-chunk truncation.
  - **ContextBudget** — per-agent defaults (planner: 3000, research: 5000,
    reviewer: 2000), overridable at construction.
  - **knowledge_embeddings** table — stores chunk embeddings with
    `embedding_hash` for incremental re-embed; auto-deleted on source reindex.
  - **Retrieval telemetry** — `telemetry_retrieval` table recording
    `retrieval_latency_ms`, `chunks_retrieved`, `chunks_selected`,
    `tokens_before`, `tokens_after`, and `compression_ratio`.
  - **CLI** — `aios knowledge retrieve "<q>" [--agent X] [--vector] [--json]`;
    `aios knowledge index --embed` for embedding-after-index.
  - **Fallback safe** — missing embeddings or unavailable provider never fail
    retrieval; keyword path is always available.

### Changed

- Scheduler now writes `TODO.md` (textual backlog with checkboxes + spinner)
  instead of rendering the Kanban board to stderr during `plan --run`. The
  Kanban visual display is deprecated; the Kanban Engine remains as internal
  API for flow enforcement and TDD gate validation.

## [0.9.4] - 2026-08-08

### Added

- **Knowledge Store** — structured, incremental knowledge layer with contracts
  (`KnowledgeSource`, `KnowledgeDocument`, `KnowledgeChunk`, `KnowledgeQuery`,
  `KnowledgeResult`), `SQLiteKnowledgeStore` backend, deterministic chunking,
  FTS5 search, and source discovery for skills, ADRs, documentation, code,
  research, and project DNA.
- **Knowledge Engine** — registerable in the Kernel, provides `index()`,
  `search()`, and `list_sources()`.
- **CLI** — `aios knowledge index` (incremental indexing by hash),
  `aios knowledge search "<query>"` (FTS5), and `aios knowledge sources`.
  Alias: `aios k`.
- **Hashing policy** — sha256 of normalized content. Same hash = skip; changed
  hash = re-chunk. Old chunks are removed, new chunks inserted
  deterministically.
- **Tests** — 38 tests covering contracts, schema, incremental indexing,
  project isolation, FTS5 search, index runs, and CLI commands.

## [0.9.3] - 2026-08-08

### Added

- **Telemetry Engine** — observes agent lifecycle/execution events via EventBus
  and persists execution records, usage (token counts), and cost data into
  `.aios/memory.db` (tables: `telemetry_executions`, `telemetry_usage`,
  `telemetry_costs`).
- **CLI** — `aios usage [--agent X] [--model Y] [--today] [--workflow Z]
  [--from DATE] [--to DATE] [--limit N] [--json]`.

### Changed

- Scheduler now writes `TODO.md` (textual backlog with checkboxes + spinner)
  instead of rendering the Kanban board to stderr during `plan --run`. The
  Kanban visual display is deprecated; the Kanban Engine remains as internal
  API for flow enforcement and TDD gate validation.

## [0.9.2] - 2026-08-08

### Added

- **Single execution contract** — `AgentTask` (input), `AgentResult` (output),
  `AgentError` (standardized error with stable codes: `VALIDATION_ERROR`,
  `RUNTIME_ERROR`, `PERMISSION_DENIED`, `TIMEOUT`, `CANCELLED`, `UNKNOWN`),
  `AgentCapabilities`, and `AgentMetadata` (name, version, timeout, retry
  policy). Every agent implements `execute(task, context) -> AgentResult`. (#6)
- **AgentExecutor as the single execution boundary** — validates the task,
  enforces capabilities (`PERMISSION_DENIED`), drives the lifecycle, and
  applies timeout, retry (transient errors only, default **no retry**), and
  cancellation centrally. Invokes `agent.execute()`; agents are executor-free,
  so recursion is structurally impossible. (#6)
- **Standardized lifecycle** — `created → validated → queued → running →
  succeeded | failed | timed_out | cancelled`, with immutable terminal states
  and timestamps/duration exposed on the result and the event bus. `running →
  running` marks a retry. The `created → created` event is the initialization
  event (not a transition) and guarantees every execution has a complete,
  deterministic sequence. (#6)
- **Two-tier lifecycle/execution events** — `agent.lifecycle.changed` (every
  state transition, with `previous_state`/`current_state`) plus
  `agent.execution.started/progress/completed/failed/timed_out/retried/
  cancelled`. Every event shares a consistent payload: `event_id`, `agent`,
  `task_id`, `correlation_id`, `executor_id` (per instance), `sequence` (per
  execution), `attempt`, `status`, `duration_ms`, `error_code`, `message`. The
  legacy `agent.execution.finished` topic was removed. (#6)
- **Capability enforcement** — `CapabilityEnforcer` validates declared
  capabilities against the canonical policy and guards read-only agents
  (Planner/Research/Reviewer) from write/shell/internet. The executor applies
  it before running; violations map to `PERMISSION_DENIED`. (#6)
- **Compliance matrix** — `tests/agent_compliance_matrix.py` declares, per
  agent, the input/output contract, capabilities, timeout, retry policy,
  required events, and error behavior. Contract, integration, and architecture
  tests are driven by it. (#6)
- **Test suites** — per-agent contract tests, integration tests via the
  executor (all 7 agents, events, retry, capability enforcement), and
  architecture checks enforcing both directions of the execution boundary and
  the single producer of `agent.*` events. (#6)
- **Workflow/CLI full compliance** — `WorkflowEngine`, `Kernel.run()`, and the
  `review`/`research` CLI commands route exclusively through the executor /
  `Kernel.run_agent()`. Rich domain APIs (`review`, `research`, `run`,
  `generate_changelog_fragment`, git ops) became private implementations. (#6)
- **Report** — `docs/reports/agent-core-compliance-report.md` with per-agent
  ✅/❌ verdicts per category.

### Changed

- `ReviewerAgent`, `ResearchAgent`, `TesterAgent`, `DocumentationAgent`, and
  `GitAgent` now expose `execute(task, context)` as their contract method and
  route all work through the AgentExecutor; their deterministic domain methods
  are private.
- Planner/Developer runtime errors now propagate so the AgentExecutor can retry
  transient failures centrally; domain failures (e.g., invalid JSON plans)
  still return a failed `AgentResult`.
- The `aios/policies/agent_capabilities.yaml` reference policy now covers all
  seven agents consistently.

## [0.9.1] - 2026-08-08

### Added

- **Researcher (first-class agent)** — `ResearchAgent` upgraded from a
  fetcher-only scaffold into a contract-bound researcher. Input is a
  `ResearchTask`; output is a validated `ResearchResult` with `sources`,
  `findings` (provenance via `evidence_source_ids`), `confidence_overall`,
  `recommendations`, and advisory `memory_candidates`. (#15)
- **Research domain contracts** — `aios.research` package with dataclasses
  (`ResearchTask`, `ResearchSource`, `Finding`, `Recommendation`,
  `MemoryCandidate`, `ResearchResult`) and schema validation enforcing
  traceability, unique ids, bounded confidence, and a 140-char summary.
- **Deterministic local collection** — `repo`/`docs` scopes are collected
  locally with `filesystem_read` only (zero-dependency, keyword scan).
- **Explicit availability status** — `web` scope without an injected fetcher
  returns `status="source_unavailable"` with no fabricated claims; `mixed`
  degrades gracefully to `status="partial"`.
- **Optional workflow front-gate** — `WorkflowEngine` accepts an optional
  `researcher`; when injected, research runs before the planner and its result
  feeds downstream agents via `ContextPacket.research`. When absent, the
  pipeline is unchanged.
- **CLI** — `aios research "<question>" [--scope repo|docs|web|mixed]
  [--json] [--output FILE]`.

### Changed

- `ResearchAgent.required_capabilities` is now `["filesystem_read"]` only.
  Internet access is a contextual capability of an injected web source fetcher,
  not a hard prerequisite of the agent.

### Notes

- `memory_candidates` are advisory output only. This version never persists
  candidates into the Memory Engine; a future admission mechanism decides what
  becomes project knowledge.
- No web provider ships in core. Web research requires injecting a fetcher
  (`Callable[[ResearchTask], list[ResearchSource]]`), keeping the core
  zero-dependency and local-first.

## [0.9.0] - 2026-08-06

Milestone release capturing the implemented work since v0.1.0. Workflows,
Plugins, and the Tester/Documentation/Git/Research agents remain **Specified** —
they are planned, not yet shipped.

### Added

- **Planner (v0.6)** — goal decomposition into ordered subtasks with priorities,
  dependencies, risks, and unknowns. Reasoning loop (max 3 iterations) with
  `ask_user` tool execution and JSON self-healing. (#4)
- **Reviewer (v0.7)** — read-only code/architecture evaluator returning a strict
  JSON verdict. Shipped as a tested component **without CLI integration**; the
  `aios review` command is future work. (#5)
- **Scheduler (v0.8)** — persistent kanban/scrum boards with SQLite storage,
  card/subtask lifecycle, TDD gate enforcement, and project isolation. (#6)
- **Reactive live board** — event-driven kanban rendering during `plan --run`
  execution, with blocked-card notifications. (#9, #10)
- **AgentExecutor** — generic execution guardrail (timeout, retry, event bus
  publishing) shared by all agents. (#3)
- **OpenCode runtime** — headless `opencode run --auto` invocation with
  capability-based permission enforcement and ai-jail sandbox. (#2, #1)
- **CLI** — `aios init`, `aios doctor --json`, Command Registry as single source
  of truth, bash/zsh completion, and the `ad` alias. (#5)
- **Memory Engine (v0.3)** — SQLite-backed conventions, decisions, patterns, and
  mistakes, stored in `.aios/memory.db`. (#1)

### Changed

- `aios plan <intent> --run` now creates a sprint board, populates the initial
  backlog, and blocks cards when the TDD gate fails (fail-fast). (#10)
- Project state moved to `.aios/memory.db`; the project manifest lives in
  `.aios/project.yaml`.
- Graceful shutdown on SIGINT/SIGTERM.

### Fixed

- CI resilience when OpenCode/ai-jail are not installed on runners.
- Console spinner cleanup and ANSI line handling to prevent vertical wrapping.
  (#8)
- Runtime timeouts tuned for long planning/execution sessions.

### Security

- Headless tool permissions are enforced in the RuntimeAdapter
  (`OPENCODE_PERMISSION`).
- OpenCode is always invoked through the ai-jail sandbox, never directly.

### Notes

- Reviewer is a tested component but is **not** exposed via the CLI or kernel
  yet.
- Workflows, the Plugin System, and the v0.9 agents (Tester, Documentation, Git,
  Research) are documented under `docs/` but **not implemented** in this
  release.
- Requires Python 3.12+. Status: **Alpha**.

[Unreleased]: https://github.com/GabrielPabloG/aiosdeck/compare/v0.9.13...main
[0.9.13]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.13
[0.9.12]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.12
[0.9.11]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.11
[0.9.10]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.10
[0.9.9]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.9
[0.9.8]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.8
[0.9.7]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.7
[0.9.4]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.4
[0.9.3]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.3
[0.9.2]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.2
[0.9.1]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.1
[0.9.0]: https://github.com/GabrielPabloG/aiosdeck/releases/tag/v0.9.0
