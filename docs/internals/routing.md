# Model Router

**Status**: Accepted
**Date**: 2026-08-08

## Context

AiosDeck agents (planner, developer, research, …) all asked the runtime for a
model implicitly. The choice was fixed at configuration time and every agent
ran the same model regardless of task. Cost and latency were uncontrolled, and
a failing model had no escape hatch.

The principle is: **context before intelligence** — the model is a function of
the task, not of the agent. The Model Router separates *model decision* from
*agent execution*: policy rules (and, later, telemetry data) pick the model,
and the agent only describes what it is doing.

## Decision

### Contracts

Every route request and decision travels through two dataclasses:

```python
class RouteInput:
    agent: str            # "planner" | "developer" | ...
    task_type: str = "code"     # "plan" | "code" | "test" | "documentation" | ...
    complexity: str = "medium"  # "low" | "medium" | "high"
    context_size: int = 0       # estimated prompt tokens
    model_override: str = ""    # explicit model (skips rules, audited)

class RouteDecision:
    provider: str
    model: str            # "provider/model" (opencode -m format)
    variant: str = ""     # --variant
    reason: str           # "policy:0" | "heuristic:default" | "explicit_override"
    estimated_cost: float = 0.0
    fallback_chain: list[dict]  # [{"provider", "model", "variant"}, ...]
    source: str = "router"      # "router" | "override"
```

`ModelRouter` is a `Protocol` with a single method `route(input) -> RouteDecision`.
`RuleBasedRouter` is the default implementation.

### Policy YAML

Routing is opt-in via `RouteConfig`, loaded from the `routing:` section of the
config YAML (plus `AIOS_ROUTING_ENABLED` / `AIOS_ROUTING_COST_CAP` env vars).
When routing is disabled (default `enabled: True`, but no rules) the runtime
behaves exactly as before — byte-identical execution.

```yaml
# ~/.config/aiosdeck/config.yaml
routing:
  enabled: true
  default_provider: ollama
  default_model: llama3
  rules:
    - agent: documentation
      complexity: low
      provider: ollama
      model: llama3
    - agent: research
      complexity: medium
      provider: anthropic
      model: claude-haiku
    - agent: planner
      complexity: high
      provider: anthropic
      model: claude-sonnet
    - agent: developer
      complexity: high
      provider: anthropic
      model: claude-sonnet
  context_limits:
    planner: 8000
    developer: 16000
  cost_cap: 5.0            # 0 = no cap
  fallback_providers:
    - provider: ollama
      model: llama3
```

Rules match on `agent` + `complexity` and honor `context_limits`
(`context_size > limit` skips the rule). The first matching rule wins with
`reason="policy:<index>"`. No match falls back to
`default_provider/default_model` with `reason="heuristic:default"`.

`cost_cap`: if a matched model's `estimated_cost` exceeds the cap, the router
re-routes to the cheapest fallback provider that fits the budget; if none fits,
it raises a `Cost cap exceeded` error instead of silently overspending.

### Pipeline

```
Agent
   │  execute(..., agent, task_type, complexity, context_size, model="")
   ▼
RuntimeEngine
   │  router.route(RouteInput(...))   # RuleBasedRouter (policy)
   ▼
RouteDecision ──► OpenCodeAdapter  (-m provider/model, --variant)
   │                 │
   │                 └── success → return output
   │                 └── RuntimeError/Timeout → next fallback_chain entry
   ▼
runtime.route_selected event  →  telemetry_routing table
```

The runtime loops over `[decision] + decision.fallback_chain`, trying each model
in order. Failures (`unavailable`, `timeout`, `budget_exceeded`) move to the
next entry; if every model fails, a typed `RouteFallbackExhausted` is raised —
the loop can never spin forever.

### Override

An explicit `model=` argument to `RuntimeEngine.execute()` skips the router
entirely and is audited with `source="override"`, `reason="explicit_override"`.
Agents never hardcode models; they pass context (agent/task_type/complexity/
context_size). Overrides are for operators and CLI tooling only.

### Ranker

`ModelRanker` is a pluggable `Protocol` for ordering routing candidates:

- `HeuristicRanker` — fixed weights (agent match, complexity, cost). Always
  available and deterministic.
- `TelemetryRanker` — post-1.0 fast-follow (data-driven: fail rate, latency,
  cost per 1k tokens from the telemetry store). Contract stub present, not
  implemented in v1.0.

### CLI

`aios route` inspects routing without executing an agent:

- `aios route explain --agent planner --task-type plan --complexity high [--json]`
  — dry-run the policy and print the decision + fallback chain.
- `aios route stats [--agent A] [--model M] [--limit N] [--records] [--json]`
  — aggregated routing telemetry, or individual decision records with `--records`.
- `aios route stats --accuracy` — compares `estimated_cost` against the actual
  cost recorded in `telemetry_costs` (when both are available).

## Status

Routing is opt-in and off by default in behavior: with no rules and no override,
execution is byte-identical to v0.9.10.
