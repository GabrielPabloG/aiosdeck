# Fire Test Manual — Stabilization v1.0

Guia para validar o núcleo estável do AiosDeck em um projeto limpo.
Testa telemetria mínima obrigatória (executions, tokens, cost), a CLI
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

## Passo 5 — Validar telemetria obrigatória (executions + tokens + cost)

As 3 tabelas mínimas obrigatórias devem existir e ter dados:

```bash
# Execuções registradas
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_executions;"

# Tokens consumidos
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_tokens;"

# Custos calculados
sqlite3 .aios/memory.db "SELECT COUNT(*) FROM telemetry_costs;"
```

Esperado: pelo menos 1 registro em cada tabela após uma execução.

Uso visível:

```bash
# Resumo de uso (tokens + custo)
aios usage

# Com filtro de limit
aios usage --limit 5
```

## Passo 6 — Validar eventos mínimos obrigatórios

Os tópicos de evento obrigatórios para cada execução:

```bash
sqlite3 .aios/memory.db "SELECT DISTINCT topic FROM telemetry_events ORDER BY topic;"
```

Esperado: os tópicos `agent.lifecycle.changed`, `agent.execution.*` (started,
completed/failed), `workflow.started`, `workflow.completed` estão presentes.

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
| 5 | `telemetry_executions` tem registros | Passo 5 |
| 6 | `telemetry_tokens` tem registros | Passo 5 |
| 7 | `telemetry_costs` tem registros | Passo 5 |
| 8 | Eventos `agent.lifecycle.*` e `agent.execution.*` publicados | Passo 6 |
| 9 | `aios usage` mostra dados | Passo 5 |
| 10 | Erros não vazam traceback | Passo 7 |
| 11 | Agentes executor-free | Passo 8 |
| 12 | Completion shell funciona | Passo 2 |
