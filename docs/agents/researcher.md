# Researcher Agent

**Status**: Implemented
**Date**: 2026-08-02
**Updated**: 2026-08-08 (v0.9.1 — first-class agent)
**Introduced**: v0.8

## Context

Some tasks require external knowledge: API documentation, library usage patterns, best practices for unfamiliar technologies. The Researcher agent collects sources and returns structured findings to inform other agents.

The Researcher is the only agent designed to touch the web, and even then only through an injected fetcher. Internet access is a **contextual capability of a web source fetcher**, not a hard prerequisite of the agent: `repo`/`docs` research works with `filesystem_read` alone.

## Decision

### In → Process → Out

```
In:  ResearchTask
     { question, scope: repo|docs|web|mixed, constraints, context_packet }
     Context Packet (project, stack, version)

Process:
  1. Collect sources
       repo/docs → deterministic local collector (filesystem_read only)
       web/mixed → injected fetcher(task) -> list[ResearchSource]
  2. Normalize and dedupe sources by URL
  3. Synthesize findings with provenance (evidence_source_ids)
       injected synthesizer, or deterministic heuristic
  4. Report status explicitly: ok | partial | source_unavailable | error

Out: ResearchResult (validated)
     { task, status, summary_short, sources, findings,
       confidence_overall, recommendations, memory_candidates }
```

The core never performs network I/O. Web collection goes through a fetcher
contract:

```
Web Research
  ↓
Fetcher Contract  (Callable[[ResearchTask], list[ResearchSource]])
  ↓
Research Adapter  (Tavily / OpenCode / plugin / future provider)
  ↓
Web tool / API / provider
```

### Output Format

```python
ResearchResult(
    task=ResearchTask(question="...", scope="mixed"),
    status="ok",                      # ok | partial | source_unavailable | error
    summary_short="Collected 3 source(s), 2 finding(s), confidence 0.72.",
    sources=[
        ResearchSource(id="local-1", title="src/auth.py",
                       url="file://src/auth.py", type="code",
                       retrieved_at="2026-08-08T...", trust_score=0.7, ...),
    ],
    findings=[
        Finding(id="F1", claim="...",
                evidence_source_ids=["local-1"], confidence=0.7, ...),
    ],
    confidence_overall=0.72,
    recommendations=[Recommendation(action="...", rationale="...", priority="low", ...)],
    memory_candidates=[MemoryCandidate(kind="pattern", content="...", confidence=0.7)],
)
```

### Availability Semantics

A missing web fetcher is never masked as a low-confidence result:

| Case | status | findings |
|------|--------|----------|
| `repo`/`docs` (local collection) | `ok` | derived from local sources |
| `web` + fetcher injected | `ok` | derived from fetched sources |
| `web` + no fetcher | `source_unavailable` | **none** — only an explicit availability recommendation |
| `mixed` + no fetcher | `partial` | local findings + explicit web-unavailable note |

A recommendation in the `source_unavailable`/`partial` cases states plainly
that web collection is unavailable; it is never presented as a research claim.

### MemoryCandidate — advisory output

```
Researcher
  ↓
MemoryCandidate      (advisory, structured)
  ↓
[future Memory admission]   (threshold, human review, classification)
  ↓
Memory Engine
```

v0.9.1 does **not** persist candidates. The agent never calls the Memory
Engine; a future admission mechanism decides what becomes project knowledge.

### Required Capabilities

- `filesystem_read` — local collection for `repo`/`docs` scopes.

Internet access is not in `required_capabilities`: it belongs to the injected
web fetcher and is only exercised when a fetcher is present.

### Cannot

- Write code
- Execute Git commands
- Run shell commands
- Modify files
- Persist to Memory Engine

### Required Skills

- `project-dna` — must understand project context to filter relevant results
- `coding-style` — must recognize patterns that match project conventions

### Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `task.created` (type: research) | Consumed | Receive a research task |
| `agent.completed` | Emitted | Research findings ready |

### Workflow Integration

`WorkflowEngine` accepts an optional `researcher`. When injected, research
runs as an optional front-gate **before the planner**, and its structured
result is exposed through `ContextPacket.research` to the planner and
developer. When no researcher is available the pipeline is unchanged —
research is never a mandatory dependency:

```
With researcher:   Research → Planner → Developer → Reviewer → Tester → Documentation → Git
Without:           Planner → Developer → Reviewer → Tester → Documentation → Git
```

### CLI

```
aios research "<question>" [--scope repo|docs|web|mixed] [--json] [--output FILE]
```

`--json` prints the full `ResearchResult`; `--output FILE` writes a JSON
report for auditing.

## Consequences

### Positive

- **Isolated, optional web access**: only a configured fetcher reaches the
  network; the core stays local-first and zero-dependency.
- **Provenance**: every finding cites its evidence sources — knowledge can be
  audited.
- **Explicit availability**: missing web capability is reported as such, never
  fabricated into a low-confidence research claim.
- **Advisory memory**: candidates are structured for a future admission
  mechanism, keeping Memory high-quality rather than an agent dump.
- **Deterministic by default**: the heuristic pipeline is fully testable
  without an LLM or network.

### Negative

- **Latency**: web fetchers add time to workflows.
- **Accuracy**: heuristic synthesis is conservative; quality depends on the
  injected fetcher/synthesizer.
- **Web providers**: no provider ships in core — a fetcher must be injected.

## Implementation Notes

- [x] Domain contracts (`ResearchTask`/`ResearchResult`/`ResearchSource`/`Finding`/`Recommendation`/`MemoryCandidate`) in `aios.research`
- [x] Schema validation enforcing traceability, unique ids, bounded confidence, 140-char summary
- [x] Deterministic local collector for `repo`/`docs`
- [x] Injected fetcher contract for `web`/`mixed`; explicit `source_unavailable` status
- [x] Optional workflow front-gate feeding `ContextPacket.research`
- [x] `aios research` CLI with `--json` and `--output`
- [ ] Web source fetcher adapter (Tavily / OpenCode / plugin) — future
- [ ] Memory admission mechanism for `memory_candidates` — future
