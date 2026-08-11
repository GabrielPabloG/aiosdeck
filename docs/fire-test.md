# Fire Test Manual — Stabilization v1.0

Guia para validar o núcleo estável do AiosDeck em um projeto limpo.
Testa telemetria mínima obrigatória (executions, routing, usage/cost), a CLI
essencial (`aios ocean`, `help`, `completion`) e a saúde do Kernel.

## Pré-requisitos

- Python 3.12+ com o pacote instalado (`pip install -e .` no repo)
- **OpenCode** e **ai-jail** instalados (`aios doctor` confirma)
- **Ollama** com modelo local puxado (ex: `llama3`) — necessário para
  execuções reais
- Shell no Linux

## Passo 0 — Instalar a branch

```bash
cd <seu-repo-aiosdeck>
git checkout feature/stable-1.0
pip install -e .
```

## Passo 1 — Criar projeto de teste descartável

```bash
mkdir -p /tmp/firetest-stable && cd /tmp/firetest-stable
git init -q
git config user.email "you@test.com" && git config user.name "You"
touch README.md && git add . && git commit -qm "init"
aios init
```

## Passo 2 — Sanidade: doctor e help

```bash
# Doctor confirma infraestrutura
aios doctor

# Help mostra todos os comandos (sem traceback)
aios help

# Completion funciona (bash e zsh)
aios completion --bash | head -5
aios completion --zsh | head -5
```

Esperado: `doctor` saudável, `help` lista todos os comandos, `completion`
gera scripts de shell válidos. Nenhum traceback Python escapa.

## Passo 3 — Ocean dashboard (mínimo de CLI)

```bash
# Visão geral (overview)
aios ocean

# Página única com saída
aios ocean --once

# JSON para consumo programático
aios ocean --json

# Páginas individuais navegáveis
aios ocean --page overview
aios ocean --page workflows
aios ocean --page agents
aios ocean --page skills
aios ocean --page knowledge
aios ocean --page usage
aios ocean --page quality
aios ocean --page settings
```

Esperado: cada página renderiza sem erro. `--json` retorna JSON válido.
Nenhum traceback.

## Passo 4 — Execução real (telemetria mínima obrigatória)

Com Ollama rodando localmente:

```bash
# Execução mínima: planner + developer
aios plan "add a hello world endpoint" --run
```

Esperado: pipeline completa (planner → developer → reviewer → tester →
documentation → git). A saída contém os stages.

## Passo 5 — Validar telemetria mínima obrigatória (executions + routing)

As 2 tabelas de telemetria mínimas obrigatórias devem existir e ter dados:

```bash
# Execuções registradas (uma por lifecycle/execution event)
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_executions;"

# Decisões de roteamento registradas (uma por runtime.route_selected event)
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_routing;"
```

Esperado: pelo menos 1 registro em cada tabela após uma execução.

Token usage e custo são gravados quando o runtime reporta `usage` no evento de
execução (provider-dependent). Quando reportados, devem ter dados:

```bash
# Tokens consumidos (presentes quando o provider reporta usage)
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_usage;"

# Custos calculados (derivados de telemetry_usage)
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_costs;"
```

Uso visível:

```bash
# Resumo de uso (execuções + tokens + custo)
aios usage

# Com filtro de limit
aios usage --limit 5
```

## Passo 6 — Validar eventos mínimos obrigatórios

Os eventos obrigatórios não são persistidos numa tabela própria: o
TelemetryEngine os consome e os evidencia nas tabelas de telemetria. Para
confirmar que os eventos foram publicados, verifique os status de execução
gravados (que refletem `agent.lifecycle.*` / `agent.execution.*`):

```bash
sqlite3 .aios/memory.db "SELECT DISTINCT status FROM telemetry_executions ORDER BY status;"
```

Esperado: os status `started`, `completed`/`succeeded`/`failed` (conforme o
run) estão presentes, além de `workflow.started`/`workflow.completed`
evidenciados pelas execuções do workflow.

## Passo 7 — Caminhos de erro

```bash
# Subcomando inválido → Usage + exit 1
aios bogus

# Comando sem argumento obrigatório → Error + exit 1
aios route

# Fora de repo → Error informativo
cd /tmp && aios ocean
```

Esperado: mensagens de erro formatadas, sem traceback Python, exit code 1.

## Passo 8 — Verificação de arquitetura (o que a v1.0 garante)

O gate oficial de arquitetura é a suíte de testes dedicada:

```bash
pytest tests/architecture/ -q
```

Esperado: **8 passed**. A suíte garante, entre outros, que os 7 agentes são
executor-free (nenhum importa ou referencia `AgentExecutor`). O re-export
público em `src/aios/agents/__init__.py` é intencional (API pública congelada)
e não é um agente importando o executor.

- `AgentTask` e `AgentResult` são o único contrato de entrada/saída de agentes.
- `HeuristicRanker` é o único ranker implementado (TelemetryRanker é post-1.0).
- Tabelas de telemetria são aditivas (`CREATE TABLE IF NOT EXISTS`).
- `RunResult` + `StageSummary` são a única interface CLI ↔ execução.

## Passo 9 — Benchmark (baseline de performance, v1.1.0)

Instrumentação de tempos de parede (wall + CPU user/system) com
`time.monotonic()`/`os.times()`. Mede antes de otimizar.

```bash
# Profile das 7 fases (startup → telemetry_flush), percentis p50/p95/p99
aios benchmark phases --json --warmup 1 --repeat 5

# Cinco comandos da superfície CLI, sem LLM (rápido/determinístico)
aios benchmark all --skip-agents --json

# Baseline versionada (geração determinística para CI/regressão)
aios benchmark all --skip-agents --output .aios/benchmarks/v1.0.0.json

# Espera real de processo do usuário (subprocesso, python -m aios --version)
aios benchmark startup --process --json
```

Esperado: JSON estruturado com `phases.*` e `commands.*` (cada um com `runs`
brutos e `summaries` por métrica — `wall_time_ms`, `cpu_user_ms`,
`cpu_system_ms`), percentis p50 ≤ p95 ≤ p99, e `skipped: true` explícito para
fases/comandos que dependem de modelo quando `--skip-agents` é usado. Nenhum
traceback. Sem `--json`/`--output`, a saída é uma tabela de texto.

Critérios: warmup é descartado (cold start não contamina), falhas de kernel ou
de comando registram duração sem abortar o benchmark (modo minimal), e o
baseline é salvo apenas com `--output`.

## Limpeza

```bash
rm -rf /tmp/firetest-stable
```

## Critérios de aceite

| # | Critério | Verificação |
|---|----------|-------------|
| 1 | `aios help` lista todos os comandos | Passo 2 |
| 2 | `aios doctor` saudável | Passo 2 |
| 3 | `aios ocean` renderiza sem erro | Passo 3 |
| 4 | Pipeline executa sem crash | Passo 4 |
| 5 | `telemetry_executions` tem ≥1 registro | Passo 5 |
| 6 | `telemetry_routing` tem ≥1 registro | Passo 5 |
| 7 | `telemetry_costs` tem registros (quando o provider reporta usage) | Passo 5 |
| 8 | Eventos `agent.lifecycle.*` e `agent.execution.*` evidenciados | Passo 6 |
| 9 | `aios usage` mostra dados | Passo 5 |
| 10 | Erros não vazam traceback | Passo 7 |
| 11 | Agentes executor-free (suíte de arquitetura 8 passed) | Passo 8 |
| 12 | Completion shell funciona | Passo 2 |
| 13 | `aios benchmark` produz baseline com percentis (p50/p95/p99) | Passo 9 |

## Known Limitations (v1.0)

- **Fases LLM exigem modelo** — as fases `plan` e `agent_exec` (e os comandos
  `plan` / `backlog run`) do `aios benchmark` só medem com um runtime/modelo
  disponível (ex: Ollama). Sem modelo, a fase falha mas registra a duração e o
  erro; com `--skip-agents`, essas fases/comandos aparecem explicitamente como
  `skipped` (não confundir com "0 ms").
- **`startup` in-process ≠ espera de processo real** — `aios benchmark` mede
  `startup` como bootstrap + `create_kernel` em processo. A espera real do
  usuário (criação de processo + imports + argparse) é medida à parte com
  `aios benchmark startup --process` (subprocesso).
- **Token tracking pode ser deferido** — `telemetry_usage` e `telemetry_costs`
  só recebem linhas quando o runtime reporta `usage` no evento de execução.
  Quando o provider não reporta tokens, `aios usage` responde com dados
  honestos (mostra as execuções registradas), mas sem linhas de token/custo.
  Os portões de telemetria obrigatórios da v1.0 são `telemetry_executions` e
  `telemetry_routing`.
- **Eventos não são persistidos numa tabela própria** — os eventos não são
  gravados numa tabela dedicada de eventos; o TelemetryEngine os consome e os
  evidencia nas tabelas de telemetria (principalmente `telemetry_executions`).
- **A tabela de tokens é `telemetry_usage`** — contagens de token vivem em
  `telemetry_usage` e custos em `telemetry_costs`.
- **Custo real pós-1.0** — `route_accuracy` via parsing de `opencode --format
  json` é deferido (ver `docs/migration-1.0.md`).
