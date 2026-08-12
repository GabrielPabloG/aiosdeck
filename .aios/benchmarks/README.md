# Benchmarks

Medições de desempenho do AiosDeck. Cada arquivo `.json` nesta pasta é um
report versionado (`schema_version: 1.1`, validável também com 1.0), com:

```bash
aios benchmark validate .aios/benchmarks/<arquivo>.json
```

## Estrutura

- `v<versão>.json` — baseline ativa da versão.
- `history/<arquivo>.json` — snapshot histórico imutável da mesma medição.
- A baseline é a referência contra a qual otimizações futuras são comparadas.

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
