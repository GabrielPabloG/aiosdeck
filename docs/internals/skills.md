# Living Skills — lifecycle and architecture

AiosDeck v0.9.6 transforms Skills from static `SKILL.md` files into **living,
measurable knowledge assets** — discovered by intent, retrieved by relevance,
used with a token budget, and measured by lifecycle telemetry.

## Lifecycle

```
indexed → retrievable → used → measured → optimized
```

| Phase | What happens |
|---|---|
| **indexed** | `SKILL.md` is discovered by the Knowledge Engine and chunked/embedded. Metadata (`triggers`, `scope`, `priority`) is persisted in `knowledge_sources.metadata_json`. |
| **retrievable** | `SkillDiscoveryService` ranks candidate skills by intent relevance. `SkillRetrievalService` fetches the most relevant chunks per skill, respecting per-agent `ContextBudget`. |
| **used** | `SkillAssembler` produces `SkillContext[]` consumed by `PromptBuilder`. The resulting prompt section includes budgeted chunks + an audit trail. |
| **measured** | `SkillUsageRecorder` emits raw `telemetry_skills` rows for every invocation: `considered`, `selected`, `used`, `relevance_score`, `tokens_contributed`. |
| **optimized** | (future) Aggregated telemetry informs trigger tuning, priority adjustments, and deprecation decisions. |

## Three distinct telemetry signals

| Signal | Meaning | When recorded |
|---|---|---|
| **considered** | Skill was a candidate in the discovery ranking | Discovery phase |
| **selected** | Skill passed the relevance threshold (`min_score`) | Discovery phase |
| **used** | Skill chunks actually entered the final prompt | Retrieval phase |

A skill may be *considered* and *selected* but not *used* (its chunks didn't fit the budget). This preserves the raw signal for future relevance tuning without premature causality claims.

## Architecture

```
User intent
   │
   ├── SkillRegistry  ──→  validated SkillMetadata[]  (filesystem, always available)
   ├── SkillDiscoveryService  ──→  ScoredSkill[]  (deterministic, explainable)
   ├── SkillRetrievalService  ──→  SkillContext[]  (chunks, budget, per-skill policy)
   ├── SkillAssembler  ──→  fallback boundary  (try/except → [] → golden path)
   ├── SkillUsageRecorder  ──→  telemetry_skills  (raw lifecycle signals)
   └── PromptBuilder  ──→  smart section  |  old static section  (backward compat)
```

Key design principles:

1. **Generic infra stays generic.** `ContextSelector`, `ContextBudget`, `KeywordRetriever`, and `VectorRetriever` are unchanged. The skill layer only calls their public API.

2. **Policy lives in the skill layer.** Per-skill chunk limits, budget allocation, and scoring weights are all in `skills/retrieval.py` and `skills/discovery.py` — never in generic retrieval.

3. **The golden path is immutable.** When discovery is unavailable or fails, `PromptBuilder` produces the exact same prompt as v0.9.5. No new failure mode reaches the `AgentExecutor`.

## Scoring algorithm

```
total = 0.50 · trigger_score + 0.30 · scope_score + 0.20 · priority_score

trigger_score = matches / len(triggers)           (0 if none declared)
scope_score   = matches / len(scope)               (0 if none declared → neutral)
priority_score= min(priority, 10) / 10

Filter: total >= min_score (default 0.25)
Sort:   desc by total, then by skill name
Limit:  top_k (default 5)
```

Every `ScoredSkill` carries its own `trigger_matches`, `scope_matches`, and `priority_score` — feeding directly into the PromptBuilder audit trail.

## Fallback contract

```
Agent.execute()
   │
   ├── skills assembler present?
   │    ├── NO  ──→ builder.build(task, context)   (v0.9.5 prompt)
   │    └── YES ──→ assemble(intent, context)
   │                  ├── ok ──→ builder.build(task, context, skill_contexts)
   │                  └── [] ──→ builder.build(task, context)
   │
   └── Prompt delivered to runtime
```

## Metadata schema

```yaml
# SKILL.md frontmatter
---
name: coding-style           # required, lowercase slug [a-z0-9-]+
description: Conventions...   # required, non-empty
triggers:                     # intent keywords
  - python
  - style
scope:                        # when the skill is relevant
  - python
  - architecture
dependencies:                 # other skill names
  - project-dna
priority: 7                   # non-negative int
version: "1"                  # string
owner: ""                     # optional
updated_at: ""                # optional
status: active                # active | deprecated
---
```

Strict validation on load — invalid skills are logged and skipped, never crash the pipeline.

## CLI

```
aios skills discover "<intent>"  [--agent NAME] [--top N] [--json]
aios skills inspect <name>       [--json]
aios skills stats                [--today | --from DATE | --to DATE] [--skill NAME] [--json]
```

## telemetry_skills schema

```sql
CREATE TABLE telemetry_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT DEFAULT '',
    correlation_id TEXT DEFAULT '',
    skill_name TEXT NOT NULL,
    skill_version TEXT DEFAULT '1',
    intent TEXT DEFAULT '',
    agent TEXT DEFAULT '',
    considered INTEGER DEFAULT 0,
    selected INTEGER DEFAULT 0,
    used INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    tokens_contributed INTEGER DEFAULT 0,
    downstream_success INTEGER,     -- nullable, raw signal
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);
```

## Related documents

- `docs/decisions/ADR-0004-skills-over-monolithic-agents.md` — Why Skills, not monolithic agents
- `docs/internals/knowledge-store.md` — How skills are indexed and chunked
- `docs/internals/retrieval.md` — How chunks are retrieved and budgeted
