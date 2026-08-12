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

## Baseline v1.0.0

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
