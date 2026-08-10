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
aios ocean --page security
aios ocean --page routing
aios ocean --page learning
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

- Agentes são executor-free: `grep -n "AgentExecutor" src/aios/agents/planner.py src/aios/agents/developer.py src/aios/agents/reviewer.py src/aios/agents/tester.py src/aios/agents/documentation.py src/aios/agents/git.py src/aios/agents/research.py` não deve achar match.
- `AgentTask` e `AgentResult` são o único contrato de entrada/saída de agentes.
- `HeuristicRanker` é o único ranker implementado (TelemetryRanker é post-1.0).
- Tabelas de telemetria são aditivas (`CREATE TABLE IF NOT EXISTS`).
- `RunResult` + `StageSummary` são a única interface CLI ↔ execução.

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
| 11 | Agentes executor-free | Passo 8 |
| 12 | Completion shell funciona | Passo 2 |

## Known Limitations (v1.0)

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
