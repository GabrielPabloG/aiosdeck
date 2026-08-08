# Fire Test Manual — Model Router v0.9.11

Guia prático para testar a v0.9.11 **"Model Router"** num projeto descartável,
sem depender da suíte de testes. Testa o fluxo real ponta a ponta: `aios route
explain` (dry-run da policy, sem agente), roteamento por policy YAML
(regras por agent/complexity, `cost_cap`, `context_limits`,
`fallback_providers`) e a telemetria de decisões (`telemetry_routing`).

## Pré-requisitos

- Python 3.12+ com o pacote instalado (`pip install -e .` no repo)
- **OpenCode** e **ai-jail** instalados (a `aios doctor` confirma) — apenas
  para o Passo 5 (`plan --run` real)
- **Ollama** com `llama3` puxado — apenas para o Passo 5 (fallback real)
- Shell no Linux

## Passo 0 — Instalar a branch

```bash
cd <seu-repo-aiosdeck>
git checkout feature/model-router
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Passo 1 — Criar um projeto de teste descartável

```bash
mkdir -p /tmp/firetest-routing && cd /tmp/firetest-routing
git init -q
git config user.email "you@test.com" && git config user.name "You"
touch README.md && git add . && git commit -qm "init"
aios init
```

## Passo 2 — Sanidade: dashboard e doctor

```bash
aios doctor
```

Confira que o `doctor` está saudável. O router **não** aparece como engine no
dashboard: ele é injetado dentro do `RuntimeEngine` a partir do `RouteConfig`.

Sem subcomando, `aios route` mostra o usage (sem traceback):

```bash
aios route
```

## Passo 3 — `aios route explain` — decisão default (dry-run, sem agente)

O router está **ativo por padrão** (`RouteConfig.enabled = True`). Com a config
default (sem regras), qualquer entrada cai no fallback determinístico:

```bash
aios route explain --agent planner
```

Esperado:

```
Provider:       ollama
Model:          ollama/llama3
Reason:         heuristic:default
Estimated cost: $0.000000
Source:         router
```

Sem regras e sem override, o modelo é sempre `ollama/llama3` — custo zero e
determinístico. Isso significa que, em execuções reais, o runtime passa
`-m ollama/llama3` ao opencode (comportamento novo da v0.9.11; o caminho
legacy sem `-m` só existe com `AIOS_ROUTING_ENABLED=0`, veja o Passo 4).

`--json` é útil para validar o schema:

```bash
aios route explain --agent planner --task-type plan --complexity high --json
```

Valide o schema:

```bash
python - <<'EOF'
import json, subprocess
out = subprocess.run(
    ["aios", "route", "explain", "--agent", "planner", "--json"],
    capture_output=True, text=True, check=True,
).stdout
d = json.loads(out)
assert set(d) == {"provider", "model", "variant", "reason",
                  "estimated_cost", "source", "fallback_chain"}
assert d["model"] == "ollama/llama3"
print("schema ok — decisão default determinística")
EOF
```

## Passo 4 — Policy YAML (regras, cost_cap, fallback)

Configure o roteamento no config do usuário:

```bash
mkdir -p ~/.config/aiosdeck
cat > ~/.config/aiosdeck/config.yaml <<'EOF'
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
  cost_cap: 5.0
  fallback_providers:
    - provider: ollama
      model: llama3
EOF
```

Agora `aios route explain` reflete a policy (sem executar agente nenhum):

```bash
aios route explain --agent planner --task-type plan --complexity high
```

Esperado:

```
Provider:       anthropic
Model:          anthropic/claude-sonnet
Variant:        high
Reason:         policy:0
Estimated cost: $...
Source:         router
Fallback chain:
  - ollama/llama3
```

Pontos críticos:
- `reason: policy:0` — a decisão é rastreável à regra exata (não mágica).
- `fallback_chain` — contém `ollama/llama3` vindo de `fallback_providers`.
- `documentation + low` → `ollama/llama3` (local, custo zero):

```bash
aios route explain --agent documentation --task-type documentation --complexity low
```

- `context_limits` — `planner` acima de 8000 tokens não bate na regra e cai na
  default:

```bash
aios route explain --agent planner --complexity high --context-size 12000
```

Esperado: `Reason: heuristic:default` (a regra de planner foi descartada).

**Desligar o router** restaura o caminho legacy (sem `-m` no opencode):

```bash
AIOS_ROUTING_ENABLED=0 aios route explain --agent planner --json
```

## Passo 5 — Execução real com fallback (requer opencode + ollama)

Com a policy do Passo 4, o planner tentaria `anthropic/claude-sonnet`. Para
testar o fallback sem chave de API, aponte uma regra para um modelo que falha:

```bash
cat > ~/.config/aiosdeck/config.yaml <<'EOF'
routing:
  enabled: true
  default_provider: ollama
  default_model: llama3
  rules:
    - agent: developer
      complexity: medium
      provider: anthropic
      model: claude-opus
  fallback_providers:
    - provider: ollama
      model: llama3
EOF
```

Rode uma execução real:

```bash
aios plan "add a health endpoint" --run
```

Esperado: o pipeline completa — o runtime tenta `anthropic/claude-opus` (falha
sem chave → `unavailable`), registra o fallback e cai no `ollama/llama3`.
A saída do workflow normal não é bloqueada pela falha do modelo primário.

Confira a decisão e o fallback na telemetria (Passo 6).

## Passo 6 — `aios route stats` e `--records`

Depois de pelo menos uma execução real, as decisões aparecem em
`telemetry_routing`:

```bash
aios route stats
```

Esperado — grupos por `agent`/`model` com contagem de rotas, fallbacks, custo
médio e contexto médio:

```
Routing stats (N groups):
  developer   ollama/llama3            routes=1    fallbacks=1 ...
```

Linhas individuais mostram a decisão + fallback:

```bash
aios route stats --records
```

Esperado: `[FALLBACK]` no registro cujo modelo primário falhou:

```
[<timestamp>] developer     ollama/llama3                   $0.000000 (policy:0) [FALLBACK]
```

Filtros e JSON:

```bash
aios route stats --agent developer --json
aios route stats --model ollama/llama3 --limit 50
```

Conferir direto no store:

```bash
sqlite3 .aios/memory.db "SELECT agent, model, reason, fallback_used FROM telemetry_routing;"
```

## Passo 7 — `aios route stats --accuracy`

Compara o custo estimado do routing com o custo real de `telemetry_costs`
(JOIN por `correlation_id` + `model`):

```bash
aios route stats --accuracy
```

Esperado: `est=$... act=$...` quando ambos existem; caso contrário a query
retorna **vazio** (sem erro) — backward-compatible antes do v0.9.11 não há
linhas de routing.

## Passo 8 — Override auditável

`model=` explícito é um contrato interno do `RuntimeEngine.execute` —
`source="override"`, `reason="explicit_override"`, pula o router. Não há flag
CLI dedicada: agentes **nunca** escolhem modelo fixo (passam contexto:
`agent`/`task_type`/`complexity`/`context_size`). O override é coberto pela
suíte:

```bash
pytest tests/test_routing_integration.py::TestRuntimeEngineRoutingIntegration::test_explicit_model_override_skips_router -q
```

## Passo 9 — Caminhos de erro

```bash
aios route                          # sem subcomando → Usage + exit 1
aios route bogus                    # subcomando desconhecido → Error + exit 1
aios route explain --bogus          # opção desconhecida → Error + exit 1
```

Nenhum traceback Python escapa.

## Verificação da arquitetura (o que a v0.9.11 muda)

- `RouteConfig` no schema (`src/aios/config/schema.py`) com `enabled`,
  `default_provider/model/variant`, `rules`, `cost_cap`, `context_limits`,
  `fallback_providers`; env `AIOS_ROUTING_ENABLED` / `AIOS_ROUTING_COST_CAP`.
- Agentes passam **contexto**, nunca `model=` fixo
  (`grep -n "model=" src/aios/agents/` não deve achar chamada com modelo hardcoded).
- Decisões determinísticas: heurística de preço fixa, `reason` rastreável
  (`policy:N` | `heuristic:default` | `explicit_override`).
- Fallback com prevenção de loop: se todos os modelos da chain falharem →
  `RouteFallbackExhausted` (nunca repete infinitamente).
- Tabela `telemetry_routing` aditiva (adicionada via `CREATE TABLE IF NOT EXISTS`);
  sem dados de routing o comportamento é idêntico ao anterior.
- `runtime.route_selected` → `telemetry_routing`; `route_accuracy` JOIN só é
  computada quando `telemetry_costs` existe.

## Limpeza

```bash
rm -rf /tmp/firetest-routing
# opcional: restaurar config do usuário
rm ~/.config/aiosdeck/config.yaml
```
