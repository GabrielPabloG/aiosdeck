# Context Layers (v0.9.9)

**Status**: Accepted
**Date**: 2026-08-08

## Context

Principle #1 of AiosDeck is **Context before Intelligence** — better context
produces better answers. v0.9.9 formalizes context as explicit, deterministic
layers instead of an ad-hoc concatenation of packet fields, while preserving
byte-identical output for any code path that does not opt in.

## Layers

Six layers, ordered by operational precedence (higher = more important):

| Layer | Precedence | Source | Guardrail |
|-------|-----------|--------|-----------|
| `task` | 5 | agent task description | yes (never truncated) |
| `user` | 4 | config file hook (future) | no |
| `project` | 3 | `ContextPacket` (language, tools, git, skills…) | no |
| `global` | 2 | config file hook (future) | no |
| `research` | 1 | `context.research.summary_short` | no |
| `retrieved` | 0 | `KnowledgeEngine.retrieve` (1 layer per chunk) | no |

Precedence has two independent dimensions:

1. **Operational** — `TASK > USER > PROJECT > GLOBAL > RESEARCH > RETRIEVED`.
   When the total exceeds the agent budget, the lowest-precedence layers are
   cut first.
2. **Guardrail (immutable)** — a layer marked `guardrail=True` (TASK, or any
   layer explicitly flagged) always wins and is **never** truncated or dropped,
   even under an infinitesimal budget.

## Components

### `aios.context.layers`

- `LayerType` — the six layer kinds.
- `LAYER_PRECEDENCE` — `{RETRIEVED: 0, RESEARCH: 1, GLOBAL: 2, PROJECT: 3,
  USER: 4, TASK: 5}`.
- `GUARDRAIL_LAYERS` — `{TASK}`.
- `Layer` — `type`, `content`, `source` (provenance: `"task"`, `"packet"`,
  `"packet.research"`, `"selector"`…), `guardrail`, `tokens`, `trace`
  (`{"source_id", "source_path", "score", "position"}` for retrieved chunks),
  `priority`. Property `is_guardrail` (flag OR type membership).
- `LayeredContext` — ordered container with `add()`, `by_type()`,
  `total_tokens()`, `to_dict()`, `is_empty`.
- `empty_layers()` — safe factory (fallback boundary).

### `aios.context.assembly` (pure functions)

- `order_layers` — stable sort by precedence, highest first.
- `dedupe_layers` — sha256 over normalized content; first-by-precedence wins;
  records `dropped_duplicate` in the audit.
- `truncate_layers` — per-layer caps first (`DEFAULT_LAYER_CAPS`), then total
  budget; guardrails never cut; reuses `_truncate_to_tokens` (word-based).
- `assemble_layers` — order → dedupe → truncate, producing a
  `ContextAssemblyResult` with a full audit trail.
- `DEFAULT_LAYER_CAPS` — `RETRIEVED=0` (bounded by the `ContextSelector`),
  `RESEARCH=1500`, `GLOBAL/PROJECT/USER=4000`, `TASK=0` (guardrail).

### `aios.context.assembler`

`ContextAssembler(knowledge=None, budget=None).assemble(task, context, *, agent)`
collects the raw layers and fits them to `ContextBudget.for_agent(agent)`.
Each collector is wrapped in the SkillAssembler fallback boundary: a failure
in one layer degrades to an empty layer, never a raised exception. The
retrieved layer excludes `_SKILL_SOURCE_TYPES` (`skill`, `project_dna`) —
those live in their own layer via the `SkillAssembler`.

### `aios.prompts.builder` + `aios.prompts.layered`

`PromptBuilder.build(task, context, skill_contexts=None, *, layered=None)`.
When `layered is None` or empty, output is **byte-identical** to v0.9.8.
When provided, the builder composes deterministic sections:

1. `## Task` (TASK layer)
2. `## Project Context` (PROJECT layer)
3. `## Memory` (reused `_memory_section`)
4. `## Research` (RESEARCH layer)
5. `[Knowledge]` (RETRIEVED layers, mirrored `[Knowledge]` format)
6. skills (`_smart_skills_section` / `_skills_section`)
7. `[Audit]` block (per-layer type/source/tokens, total, budget, truncated,
   dropped_duplicates)

Layers carry plain-data content; formatting is the builder's job.

## Wiring

`aios.cli.main._build_context_assembler` mirrors `_build_skill_assembler`:
it reads the `knowledge` engine and returns a `ContextAssembler`, falling back
to `ContextAssembler(knowledge=None)` on any failure. The assembler is
injected into `DeveloperAgent` and `PlannerAgent`; each agent calls
`assemble(task, context, agent=self.name)` and passes the result as
`layered=` to the `PromptBuilder`. When the assembler is absent, `layered=None`
keeps the pre-v0.9.9 prompt.

## Debugging

```
aios plan "add OAuth2 login" --debug-context
aios plan "add OAuth2 login" --debug-context --json
```

Renders the layer tree in precedence order (type, source, tokens, guardrail,
trace) plus the audit trail, or the JSON form of the `ContextAssemblyResult`.

## Design Decisions

- **Opt-in, byte-identical fallback** — no configuration change means no
  behavioral change; `layered=None` produces the exact v0.9.8 string.
- **Absolute per-layer caps, not percentages** — deterministic and easy to
  reason about.
- **Guardrails are immutable** — TASK and any flagged layer survive any budget.
- **Single audit point** — `ContextAssemblyResult` is the only audit carrier,
  surfaced in the prompt `[Audit]` block and `--debug-context`.
- **Retrieved is the general layer** — ADR/docs/code live there; skills and
  project DNA stay in the `SkillAssembler` path.
- **Fail-safe, never fail** — missing config, empty research, or a broken
  retriever all degrade to an empty layer.
