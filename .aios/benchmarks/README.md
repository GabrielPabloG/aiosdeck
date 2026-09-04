# Benchmarks

Medições de desempenho do AiosDeck. Cada arquivo `.json` nesta pasta é um
report versionado (`schema_version: 1.1`, validável também com 1.0), com:

```bash
aios benchmark validate .aios/benchmarks/<arquivo>.json
```

## Estrutura

- `v<versão>.json` — baseline ativa da versão (modo `full`).
- `v<versão>-bare.json` — baseline do modo `bare` (latência pura de modelo) da
  mesma versão, em arquivo separado para não colidir com a baseline `full`.
- `v<versão>-<sufixo>.json` (ex.: `-qwen-local`) — registros adicionais
  não-oficiais (stress de hardware, variações de ambiente), fora das métricas
  de referência.
- `history/<arquivo>.json` — snapshot histórico imutável da mesma medição.
- A baseline é a referência contra a qual otimizações futuras são comparadas.

## Modos de benchmark

`aios benchmark phases --bare-task` substitui as fases `plan`/`agent_exec`
(que rodam o agente completo) por um **probe restrito direto no runtime**:
prompt fixo, sem skills, sem capabilities e com permissions vazias — todo tool
é negado estruturalmente. O resultado é a latência pura do modelo (sem retry
de parsing, sem agente, sem produto).

- Envelope: `benchmark_mode: "bare"` e `task_prompt_type: "restricted_ok"`.
- Resultado (`plan`/`agent_exec`): `tool_calls_count: 0` e `is_read_only: true`
  por construção, e `model` com a decisão de routing efetiva da fase.
- O probe resolve o modelo da **mesma decisão de routing da fase** (o mesmo
  `RouteInput` que o agente usaria), então full-vs-bare nunca comparam modelos
  diferentes — nem mesmo com regras de routing específicas por agente.
- Se a resposta não for "OK"-ish, um `warnings[]` é registrado no resultado —
  nunca falha a medição (a garantia é o permission vazio, não o texto).

Reprodução do modo bare:

```bash
export AIOS_OLLAMA_MODEL=llama3.2
aios benchmark phases --bare-task --output .aios/benchmarks/v1.0.0-bare.json
aios benchmark validate .aios/benchmarks/v1.0.0-bare.json
```

Runtime-dependent benchmarks require a fixed local Ollama model configuration.
Comparações só são válidas com o mesmo modelo e ambiente (`system_info`).

## Baseline v1.1.1 (ativa)

- **Arquivos**: `.aios/benchmarks/v1.1.1.json` (full) e
  `.aios/benchmarks/v1.1.1-bare.json` (bare — o primeiro da história), com
  snapshots em `history/`.
- **Versão AiosDeck**: 1.1.1 (`git_commit` registrado no report).
- **Runtime**: **opencode-go**, modelo `qwen3.8-flash` (routing do manifest;
  `runtime_info` é config-reportada — limitação 34.1 do `compare`).
- **Modos**: `full` (`repeat: 10`, `warmup: 1`) e `bare` (`repeat: 5`,
  `warmup: 1`).

### Reprodução

```bash
aios benchmark all --output .aios/benchmarks/v1.1.1.json
aios benchmark phases --bare-task --output .aios/benchmarks/v1.1.1-bare.json
aios benchmark validate .aios/benchmarks/v1.1.1.json
aios benchmark validate .aios/benchmarks/v1.1.1-bare.json
```

p50 (ms) — commands, modo `full`:

| Target    | v1.1.1   |
| --------- | -------- |
| dashboard | 101.40   |
| doctor    | 1960.43  |
| skills    | 100.91   |
| memory    | 96.54    |
| plan*     | 14946.75 |
| backlog*  | 98.38    |

p50 (ms) — phases, modo `bare` (latência pura):

| Target          | v1.1.1  |
| --------------- | ------- |
| startup         | 2.55    |
| kernel_init     | 105.74  |
| context_load    | 0.00    |
| skill_load      | 0.31    |
| plan*           | 5174.61 |
| agent_exec*     | 5494.21 |
| telemetry_flush | 5.00    |

\* runtime-dependent (inclui inferência do modelo roteado).

**Comparação com v1.1.0**: o runtime ativo mudou (`ollama/llama3.2` →
`opencode-go/qwen3.8-flash`), então `aios benchmark compare` contra a baseline
full de v1.1.0 dispara exit 2 (divergência de ambiente) — os deltas são
cross-environment e não valem como sinal de regressão. v1.1.1 é a nova
referência. O par full↔bare no mesmo commit (`32d7176`) quantifica o overhead
de orquestração: `plan` 14.9 s (full) vs 5.2 s (bare).

### Registro de stress de hardware (não-oficial)

- **Arquivo**: `.aios/benchmarks/v1.1.1-qwen-local.json` — mesma versão
  roteada via Ollama local (`qwen-opencode`), mantida como registro histórico
  de stress do hardware (`plan` p50 ≈ 17.0 s, p95 com outlier ≈ 198 s sob
  contenção local).
- **Não** participa das métricas oficiais de referência; a baseline é
  `v1.1.1.json`.

## Baseline v1.1.0 (histórica)

- **Arquivo**: `.aios/benchmarks/v1.1.0.json` (snapshot em `history/v1.1.0.json`).
- **Versão AiosDeck**: 1.1.0 (`git_commit` registrado no report).
- **Runtime**: Ollama local, modelo **fixado** `llama3.2`, host `http://localhost:11434`.
- **Data**: `timestamp` registrado no report.
- **Mode**: `full` (`benchmark_mode: "full"`, `repeat: 5`, `warmup: 1`).

### Reprodução

```bash
export AIOS_OLLAMA_MODEL=llama3.2          # modelo fixado da baseline
aios benchmark all --output .aios/benchmarks/v1.1.0.json
aios benchmark validate .aios/benchmarks/v1.1.0.json
```

p50 (ms) vs v1.0.0 (sem regressão Core, compare exit 0):

| Target    | v1.0.0 | v1.1.0 | Δ      |
| --------- | ------ | ------ | ------ |
| dashboard | 65.62  | 68.0   | +3.6%  |
| doctor    | 66.00  | 61.0   | -7.5%  |
| skills    | 65.81  | 64.6   | -1.8%  |
| memory    | 65.48  | 65.9   | +0.7%  |
| plan*     | 1152.68| 1135.1 | -1.5%  |
| backlog*  | 67.63  | 73.8   | +9.1%  |

\* runtime-dependent (inclui inferência do modelo local).

## Baseline v1.0.0 (histórica)

- **Arquivo**: `.aios/benchmarks/v1.0.0.json` (snapshot em `history/v1.0.0.json`).
- **Versão AiosDeck**: 1.0.0 (`git_commit` registrado no report).
- **Runtime**: Ollama local, modelo **fixado** `llama3.2`, host `http://localhost:11434`.
- **Data**: `timestamp` registrado no report.

### Reprodução

Ambiente executado para esta baseline:

- Python 3.14.4 (projeto requer `>=3.12`; fixar a mesma versão ao comparar).
- SO/distro/kernel/CPU/RAM: registrados em `system_info` do report
  (`distro`, `kernel`, `cpu`, `cpu_count`, `memory_mb`).

Passos:

```bash
export AIOS_OLLAMA_MODEL=llama3.2          # modelo fixado da baseline
aios benchmark all --output .aios/benchmarks/v1.0.0.json
aios benchmark validate .aios/benchmarks/v1.0.0.json
```

Runtime-dependent benchmarks require a fixed local Ollama model configuration.
Comparações só são válidas com o mesmo modelo e ambiente (`system_info`).

### Categorias de medição

| Categoria         | Fase/Comando        | Natureza        |
| ----------------- | ------------------- | --------------- |
| Core              | startup, kernel_init, context_load, skill_load, telemetry_flush | AiosDeck |
| Core              | dashboard, doctor, skills, memory | AiosDeck |
| Runtime-dependent | plan                | AiosDeck + Ollama |
| Runtime-dependent | backlog             | AiosDeck + Ollama |

**Atenção**: `plan`, `agent_exec` e `backlog` incluem o tempo de inferência do
modelo local. Variação nesses cenários pode ser variação de modelo/CPU — não
é, por si só, regressão do AiosDeck. Ao usar `aios benchmark compare`, desconfie
de variação de ambiente antes de interpretar como regressão.

## Comparação (aios benchmark compare)

`aios benchmark compare` confronta uma baseline contra um report atual e
classifica cada `(group, target)` em **Core** (commitável) ou
**Runtime-dependent** (corroborativo). Match por `(group, target)` via
`summaries.wall_time_ms` (gate em p50 vs `--threshold`, default 10%).

```bash
# forma determinística (2 arquivos, sem modelo/rede — recomendada para CI)
aios benchmark compare baseline.json current.json

# forma live (1 arquivo): mede o benchmark atual (phases completo) e compara
aios benchmark compare baseline.json
aios benchmark compare baseline.json --skip-agents   # apenas fases Core
```

Categorias:

| Categoria         | Match                                                          |
| ----------------- | -------------------------------------------------------------- |
| Core              | todo o resto (startup, kernel_init, context_load, skill_load, telemetry_flush, dashboard, doctor, skills, memory) |
| Runtime-dependent | `(phases, plan)`, `(phases, agent_exec)`, `(commands, plan)`, `(commands, backlog)` |

Exit codes (precedência `2 > 1 > 0`):

- `0` — sem regressão Core, ambiente compatível;
- `1` — regressão Core acima do threshold;
- `2` — divergência de ambiente/runtime (`system_info` cpu_count/cpu/distro/
  kernel/python e/ou `runtime_info` provider/model/host).

Regras:

- Alvo ausente num dos lados → `skipped` (nunca regressão).
- Runtime-dependent regredido → `warning` apenas, nunca falha Core.
- Divergência de ambiente/runtime dispara `exit 2` **mesmo com regressão Core**:
  uma regressão medida em ambiente incompatível nunca é reportada como real
  (limitação da decisão 34.1 — `runtime_info` é config-reportada, não o modelo
  efetivo do router).
- Live run fica marcado no report (`compare.live_run: true`) e é corroborativo
  apenas (depende de runtime). A forma de 2 arquivos é a determinística para
  CI/reprodutibilidade.

O output `--json` é um report de benchmark válido: `results[]` reusa o group
original de cada target com os runs atuais, mais extras em nível de result
(`baseline_p50_ms`, `current_p50_ms`, `delta_pct`, `verdict`, `category`) e uma
chave top-level `compare` com o resumo e o `exit_code`.

## Nota de comparabilidade — runtime agent selection

Desde "select opencode build agent for write-capable runs", as fases `full`
com acesso concedido de escrita/shell (developer, tester, documentation) rodam
sob `--agent build`. Baselines até v1.1.0 foram medidas sem essa seleção:
qualquer comparação contra elas é cross-environment e exige baseline nova
rotulada. O modo `bare` não é afetado (permissions vazias ⇒ nenhuma flag é
adicionada ao probe).
